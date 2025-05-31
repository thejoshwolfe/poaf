const std = @import("std");
const assert = std.debug.assert;
const File = std.fs.File;

const FileType = @import("./common.zig").FileType;
const validateFileName = @import("./common.zig").validateFileName;
const Crc32 = @import("./common.zig").Crc32;
const readTypeNameSizeAndName = @import("./common.zig").readTypeNameSizeAndName;
const decompressAndHash = @import("./common.zig").decompressAndHash;
const buffer_size = @import("./common.zig").buffer_size;

const SliceReader = @import("./SliceReader.zig");
const BufferedSliceReader = std.io.BufferedReader(buffer_size, SliceReader.Reader);
const SliceDecompressor = std.compress.flate.Decompressor(BufferedSliceReader.Reader);

pub const IndexReader = struct {
    file: File,
    file_name_buf: [16383]u8 = undefined,

    index_location: usize = undefined,
    index_crc32: u32 = undefined,
    index_hasher: Crc32 = .init(),
    index_slice_reader: SliceReader = undefined,
    index_buffered_reader: BufferedSliceReader = undefined,
    index_decompressor: SliceDecompressor = undefined,

    stream_start_offset: u64 = 4,
    skip_bytes: u64 = 0,

    pub fn init(self: *@This()) !void {
        const size = try self.file.getEndPos();
        if (size == 0) return error.EmptyOrUnseekableFile;
        if (size < 24) return error.MalformedInput; // Truncated or not a poaf archive.
        const archive_footer_location = size - 16;
        try self.file.seekTo(archive_footer_location);

        // ArchiveFooter
        const archive_footer = try self.file.reader().readStructEndian(ArchiveFooter, .little);
        if (archive_footer.footer_signature != 0xCFE9EE) return error.MalformedInput; // Truncated or not a poaf archive.
        const computed_checksum: u8 = @truncate(0 + //
            ((archive_footer.index_location >> 0x00) & 0xff) + //
            ((archive_footer.index_location >> 0x08) & 0xff) + //
            ((archive_footer.index_location >> 0x10) & 0xff) + //
            ((archive_footer.index_location >> 0x18) & 0xff) + //
            ((archive_footer.index_location >> 0x20) & 0xff) + //
            ((archive_footer.index_location >> 0x28) & 0xff) + //
            ((archive_footer.index_location >> 0x30) & 0xff) + //
            ((archive_footer.index_location >> 0x38) & 0xff) + //
            0 //
        );
        if (archive_footer.footer_checksum != computed_checksum) return error.MalformedInput; // footer_checksum incorrect
        if (!(6 <= archive_footer.index_location and archive_footer.index_location < archive_footer_location)) return error.MalformedInput; // index_location out of bounds
        self.index_location = archive_footer.index_location;
        self.index_crc32 = archive_footer.index_crc32;

        // Index Region
        self.index_slice_reader = SliceReader{
            .source = self.file,
            .start = self.index_location,
            .end = archive_footer_location,
        };
        self.index_buffered_reader = .{ .unbuffered_reader = self.index_slice_reader.reader() };
        self.index_decompressor = std.compress.flate.decompressor(self.index_buffered_reader.reader());
    }

    pub const Item = struct {
        file_type: FileType,
        file_name: []const u8,
        jump_location: u64 = undefined,
        file_size: u64 = undefined,
        contents_crc32: u32 = undefined,
        stream_start_offset: u64 = 0,
        skip_bytes: u64 = 0,

        pub fn readInfo(self: *const @This()) ReadInfo {
            return .{
                .stream_start_offset = self.stream_start_offset,
                .skip_bytes = self.skip_bytes,
                .file_size = self.file_size,
                .contents_crc32 = self.contents_crc32,
            };
        }
    };

    pub const ReadInfo = struct {
        stream_start_offset: u64,
        skip_bytes: u64,
        file_size: u64,
        contents_crc32: u32,
    };

    pub const ContentsStream = struct {
        slice_reader: SliceReader = undefined,
        buffered_reader: BufferedSliceReader = undefined,
        decompressor: SliceDecompressor = undefined,
        file_size: u64 = undefined,
        hasher: Crc32 = .init(),
        contents_crc32: u32 = undefined,
        remaining_in_chunk: u16 = 0,
        last_chunk: bool = false,

        pub const ReadError = SliceDecompressor.Reader.Error || error{MalformedInput};
        pub const Reader = std.io.Reader(*@This(), ReadError, readFn);
        pub fn reader(self: *@This()) Reader {
            return .{ .context = self };
        }
        pub fn readFn(self: *@This(), buffer: []u8) ReadError!usize {
            if (self.remaining_in_chunk == 0) {
                // EOF checks.
                if (self.last_chunk) {
                    // TODO: check file_size and crc32.
                    return 0;
                }

                // chunk_size
                self.remaining_in_chunk = try self.decompressor.reader().readInt(u16, .little);
                self.last_chunk = self.remaining_in_chunk < 0xffff;
            }

            // chunk
            const slice = buffer[0..@min(self.remaining_in_chunk, buffer.len)];
            const amt = try self.decompressor.read(slice);
            self.remaining_in_chunk -= @intCast(amt);
            return amt;
        }
    };

    pub fn next(self: *@This()) !?Item {
        // IndexItem
        var index_item_buf: [22]u8 = undefined;
        decompressAndHash(
            &self.index_decompressor,
            &self.index_hasher,
            &index_item_buf,
        ) catch |err| switch (err) {
            error.EndOfStream => {
                // End of the Index Region.
                if (self.index_decompressor.unreadBytes() > 0) return error.MalformedInput; // Index Region compression stream overlaps ArchiveFooter.
                if (self.index_hasher.final() != self.index_crc32) return error.MalformedInput; // index_crc32 mismatch.
                return null;
            },
            else => return err,
        };
        var item = try readTypeNameSizeAndName(
            Item,
            &self.index_decompressor,
            &self.index_hasher,
            &self.file_name_buf,
            index_item_buf[20..22],
        );
        item.jump_location = std.mem.readInt(u64, index_item_buf[0..8], .little);
        item.file_size = std.mem.readInt(u64, index_item_buf[8..16], .little);
        item.contents_crc32 = std.mem.readInt(u32, index_item_buf[16..20], .little);

        // precompute stream_start_offset and skip_bytes.
        if (item.jump_location > 0) {
            self.stream_start_offset = item.jump_location;
            self.skip_bytes = 0;
        } else {
            // Skip the corresponding DataItem's fields before the contents.
            self.skip_bytes += 4 + item.file_name.len;
        }
        item.stream_start_offset = self.stream_start_offset;
        item.skip_bytes = self.skip_bytes;
        // For the next item, skip the file_contents of this item.
        const chunking_overhead = 2 * (@divTrunc(item.file_size, 0xFFFF) + 1);
        self.skip_bytes += item.file_size + chunking_overhead;
        // Also skip the corresponding DataItem's fields after the contents.
        self.skip_bytes += 4;

        return item;
    }

    pub fn contentsStream(self: *@This(), info: ReadInfo, out: *ContentsStream) !void {
        // Jump into the Data Region.
        out.slice_reader = SliceReader{
            .source = self.file,
            .start = info.stream_start_offset,
            .end = self.index_location, // We don't know this is the end, but it's an upper bound.
        };
        out.buffered_reader = .{ .unbuffered_reader = out.slice_reader.reader() };
        out.decompressor = std.compress.flate.decompressor(out.buffered_reader.reader());

        // Skip until the start of the chunked contents we're looking for.
        try out.decompressor.reader().skipBytes(info.skip_bytes, .{});

        // We'll need these at the end.
        out.file_size = info.file_size;
        out.contents_crc32 = info.contents_crc32;
    }
};

const ArchiveFooter = packed struct {
    index_crc32: u32,
    index_location: u64,
    footer_checksum: u8,
    footer_signature: u24,
};
comptime {
    std.debug.assert(@sizeOf(ArchiveFooter) == 16);
}

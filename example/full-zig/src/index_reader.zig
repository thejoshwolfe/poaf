const std = @import("std");
const assert = std.debug.assert;
const Reader = std.io.AnyReader;
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

    data_slice_reader: SliceReader = undefined,
    data_buffered_reader: BufferedSliceReader = undefined,
    data_decompressor: SliceDecompressor = undefined,

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

    pub fn readItemContents(self: *@This(), item: *const Item, writer: anytype) !usize {
        // Jump into the Data Region.
        // TODO: what now?
        _ = self;
        _ = item;
        _ = writer;
        @panic("TODO: open a stateful stream of the contents?");
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

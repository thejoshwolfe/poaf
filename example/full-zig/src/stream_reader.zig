const std = @import("std");
const assert = std.debug.assert;
const Reader = std.io.AnyReader;

const FileType = @import("./common.zig").FileType;
const validateFileName = @import("./common.zig").validateFileName;
const Crc32 = @import("./common.zig").Crc32;
const readTypeNameSizeAndName = @import("./common.zig").readTypeNameSizeAndName;
const decompressAndHash = @import("./common.zig").decompressAndHash;
const buffer_size = @import("./common.zig").buffer_size;

pub const BufferedReader = std.io.BufferedReader(buffer_size, std.io.AnyReader);
pub const StreamReader = struct {
    stream: *BufferedReader,
    file_name_buf: [16383]u8 = undefined,

    stream_decompressor: std.compress.flate.Decompressor(BufferedReader.Reader) = undefined,
    data_item_hasher: Crc32 = .init(),
    streaming_contents_mode: StreamingContentsMode = undefined,
    // TODO: index verification fields.

    pub fn init(self: *@This()) !void {
        // ArchiveHeader
        var header_buf: [4]u8 = undefined;
        try self.stream.reader().readNoEof(&header_buf);
        if (!std.mem.eql(u8, &header_buf, "\xBE\xF6\xF0\x9F")) return error.MalformedInput; // Not a poaf archive.

        // Streaming
        self.stream_decompressor = std.compress.flate.decompressor(self.stream.reader());
    }

    pub const Item = struct {
        file_type: FileType,
        file_name: []const u8,
    };

    pub fn next(self: *@This()) !?Item {
        // DataItem
        var data_item_buf: [4]u8 = undefined;
        decompressAndHash(
            &self.stream_decompressor,
            &self.data_item_hasher,
            &data_item_buf,
        ) catch |err| switch (err) {
            error.EndOfStream => {
                // End of the Data Region.
                // TODO: sometimes verify the Index Region.
                return null;
            },
            else => return err,
        };
        const streaming_signature = std.mem.readInt(u16, data_item_buf[0..2], .little);
        if (streaming_signature != 0xACDC) return error.MalformedInput; // expected DataItem.streaming_signature
        const item = try readTypeNameSizeAndName(
            Item,
            &self.stream_decompressor,
            &self.data_item_hasher,
            &self.file_name_buf,
            data_item_buf[2..4],
        );
        self.streaming_contents_mode = switch (item.file_type) {
            .file, .posix_executable => .start,
            .directory => .directory,
            .symlink => .symlink,
        };

        return item;
    }

    pub fn skipItem(self: *@This()) !void {
        // Skip the DataItem.
        // TODO: don't put this on the stack at all. Use some kind of null writer.
        var buf: [0xffff]u8 = undefined;
        var ignore_me = std.io.fixedBufferStream(&buf);
        while (0 < try self.readItemContents(ignore_me.writer())) {
            ignore_me.seekTo(0) catch unreachable;
        }
    }
    pub fn readItemContents(self: *@This(), writer: anytype) !usize {
        // DataItem.chunk_size
        assert(self.streaming_contents_mode != .done); // Item is already done.
        var chunk_size_buf: [2]u8 = undefined;
        decompressAndHash(
            &self.stream_decompressor,
            &self.data_item_hasher,
            &chunk_size_buf,
        ) catch |err| switch (err) {
            error.EndOfStream => {
                // Stream split.
                if (self.streaming_contents_mode != .start) return error.MalformedInput; // Unexpected end of compression stream in Data Region.

                // We need to salvage any overrun from the previous decompressor and carry it forward to the next.
                // I could not find a way to do this through the public API,
                // but it turns out that everything we need to make this possible is contained in the bits field.
                // This works as of Zig 0.14.0.
                const bits = self.stream_decompressor.bits;
                self.stream_decompressor = .{ .bits = bits };

                // Now retry the read.
                try decompressAndHash(
                    &self.stream_decompressor,
                    &self.data_item_hasher,
                    &chunk_size_buf,
                );
            },
            else => return err,
        };
        const chunk_size = std.mem.readInt(u16, &chunk_size_buf, .little);
        switch (self.streaming_contents_mode) {
            .start => {
                self.streaming_contents_mode = .middle;
            },
            .middle => {},
            .directory => {
                if (chunk_size > 0) return error.MalformedInput; // Directory must have empty contents.
            },
            .symlink => {
                if (chunk_size > 4095) return error.MalformedInput; // Symlink target too long.
            },
            .done => unreachable, // Checked above.
        }

        // DataItem.chunk
        var chunk_buf: [0xffff]u8 = undefined;
        const chunk = chunk_buf[0..chunk_size];
        try self.stream_decompressor.reader().readNoEof(chunk);
        self.data_item_hasher.update(chunk);
        // TODO: self.contents_hash.update(chunk);

        // Return the chunk.
        try writer.writeAll(chunk);

        if (chunk.len == 0) {
            // DataItem.streaming_crc32
            const streaming_crc32 = try self.stream_decompressor.reader().readInt(u32, .little);
            if (streaming_crc32 != self.data_item_hasher.final()) return error.MalformedInput; // streaming_crc32 mismatch.
            self.streaming_contents_mode = .done;
        }

        return chunk.len;
    }
};

const StreamingContentsMode = enum {
    /// Have not read any contents yet.
    /// There may be a stream split immediately in front of the cursor.
    start,
    /// There must not be a stream split.
    middle,
    /// There must be 0 bytes left in the contents, because this is a directory.
    directory,
    /// This is a symlink and we haven't read the target yet.
    symlink,
    /// We've found the last chunk. The caller should know not to call the read function anymore.
    done,
};

//! By convention, root.zig is the root source file when making a library. If
//! you are making an executable, the convention is to delete this file and
//! start with main.zig instead.

const std = @import("std");
const assert = std.debug.assert;
const Reader = std.io.AnyReader;

const SliceReader = @import("./slice_reader.zig").SliceReader;

pub const FileType = enum(u2) {
    file = 0,
    posix_executable = 1,
    directory = 2,
    symlink = 3,
};

pub const Mode = enum {
    /// Iterate through the whole archive from start to finish returning a DataItem from next().
    /// The last call to next() performs a verification of the index and may return an error instead of null.
    stream,
    /// Iterate through just the Data Region returning a DataItem from next().
    /// The last call to next() stops reading the input at the end of the Data Region without verifying the index.
    stream_no_verify,
    /// Test at runtime if the input is seekable and if so iterate through the Index Region,
    /// otherwise iterate through the Data Region.
    /// Returns a IndexItem from next(), however, only some fields may have undefined values.
    /// Check archive.isReadingIndex() or item.hasIndexFields() to determine whether certain fields are safe to read.
    /// Does not verify the index.
    index_or_stream_fallback,
    /// Iterate through the Index Region returning an IndexItem from next().
    /// If the input is not seekable, an error is returned from init().
    /// Does not verify the index.
    index_or_error,
};

pub fn archive(comptime mode: Mode, pointer_to_stream: anytype) Archive(mode, @TypeOf(pointer_to_stream.*)) {
    return .{ .stream = pointer_to_stream };
}

pub fn Archive(comptime mode: Mode, comptime StreamType: type) type {
    return struct {
        stream: *StreamType,

        file_name_buf: [16383]u8 = undefined,

        mode_specific: switch (mode) {
            .stream => struct {
                stream_decompressor: StreamDecompressor = undefined,
                data_item_hasher: Crc32 = .init(),
                streaming_contents_mode: StreamingContentsMode = undefined,
                // TODO: index verification fields.
            },
            .stream_no_verify => struct {
                stream_decompressor: StreamDecompressor = undefined,
                data_item_hasher: Crc32 = .init(),
                streaming_contents_mode: StreamingContentsMode = undefined,
            },
            .index_or_stream_fallback => struct {
                is_stream_fallback: bool = true,

                // stream fallback:
                stream_decompressor: StreamDecompressor = undefined,
                data_item_hasher: Crc32 = .init(),
                streaming_contents_mode: StreamingContentsMode = undefined,

                // index:
                data_slice_reader: SliceReader(StreamType) = undefined,
                data_decompressor: SliceDecompressor = undefined,

                index_location: usize = undefined,
                index_crc32: u32 = undefined,
                index_hasher: Crc32 = .init(),
                index_slice_reader: SliceReader(StreamType) = undefined,
                index_decompressor: SliceDecompressor = undefined,

                stream_start_offset: u64 = 4,
                skip_bytes: u64 = 0,
            },
            .index_or_error => struct {
                data_slice_reader: SliceReader(StreamType) = undefined,
                data_decompressor: SliceDecompressor = undefined,

                index_location: usize = undefined,
                index_crc32: u32 = undefined,
                index_hasher: Crc32 = .init(),
                index_slice_reader: SliceReader(StreamType) = undefined,
                index_decompressor: SliceDecompressor = undefined,

                stream_start_offset: u64 = 4,
                skip_bytes: u64 = 0,
            },
        } = .{},

        pub const SliceDecompressor = std.compress.flate.Decompressor(SliceReader(StreamType).Reader);
        pub const StreamDecompressor = std.compress.flate.Decompressor(StreamType.Reader);

        pub fn init(self: *@This()) !void {
            // ArchiveHeader
            var header_buf: [4]u8 = undefined;
            try self.stream.reader().readNoEof(&header_buf);
            if (!std.mem.eql(u8, &header_buf, "\xBE\xF6\xF0\x9F")) return error.MalformedInput; // Not a poaf archive.

            // Determine strategy
            switch (mode) {
                .stream, .stream_no_verify => {},
                .index_or_stream_fallback, .index_or_error => {
                    attempt_seeking: {
                        const size = self.stream.getEndPos() catch break :attempt_seeking;
                        if (size == 0) {
                            // Even when getEndPos() succeeds, it can give 0 if the fd is a pipe (like stdin).
                            // Since we've already successfully read 4 bytes, we know that a 0 is not a real size.
                            break :attempt_seeking;
                        }
                        if (size < 24) return error.MalformedInput; // Archive truncated?
                        const archive_footer_location = size - 16;
                        self.stream.seekTo(archive_footer_location) catch break :attempt_seeking;
                        // At this point, we know seeking works.
                        if (mode == .index_or_stream_fallback) self.mode_specific.is_stream_fallback = false;

                        // ArchiveFooter
                        const archive_footer = try self.stream.reader().readStructEndian(ArchiveFooter, .little);
                        if (archive_footer.footer_signature != 0xCFE9EE) return error.MalformedInput; // Archive truncated?
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
                        self.mode_specific.index_location = archive_footer.index_location;
                        self.mode_specific.index_crc32 = archive_footer.index_crc32;

                        // Index Region
                        self.mode_specific.index_slice_reader = SliceReader(StreamType){
                            .source = self.stream,
                            .start = self.mode_specific.index_location,
                            .end = archive_footer_location,
                        };
                        self.mode_specific.index_decompressor = std.compress.flate.decompressor(self.mode_specific.index_slice_reader.reader());
                        // No Data Region yet.
                        return;
                    }
                    // Seeking does not work.
                    if (mode == .index_or_error) return error.SeekingNotSupported;
                    // Fallback to streaming.
                },
            }

            // Streaming
            self.mode_specific.stream_decompressor = std.compress.flate.decompressor(self.stream.reader());
        }

        pub fn isReadingIndex(self: *const @This()) bool {
            // Return not is streaming.
            return !switch (mode) {
                .stream, .stream_no_verify => true,
                .index_or_stream_fallback => self.mode_specific.is_stream_fallback,
                .index_or_error => false,
            };
        }

        pub const Item = switch (mode) {
            .stream, .stream_no_verify => DataItem,
            .index_or_stream_fallback, .index_or_error => IndexItem,
        };
        pub const DataItem = struct {
            file_type: FileType,
            file_name: []const u8,

            pub const hasIndexFields = @compileError("Unsure if this API would ever be useful. Please open a bug report requesting this function return false instead of give a compile error.");
        };
        pub const IndexItem = struct {
            file_type: FileType,
            file_name: []const u8,
            jump_location: u64 = undefined,
            file_size: u64 = undefined,
            contents_crc32: u32 = undefined,
            stream_start_offset: u64 = 0,
            skip_bytes: u64 = 0,

            pub fn hasIndexFields(self: *const @This()) bool {
                return self.stream_start_offset != 0 and self.skip_bytes != 0;
            }
        };

        pub fn next(self: *@This()) !?Item {
            // If streaming
            if (switch (mode) {
                .stream, .stream_no_verify => true,
                .index_or_stream_fallback => self.mode_specific.is_stream_fallback,
                .index_or_error => false,
            }) {
                // DataItem
                var data_item_buf: [4]u8 = undefined;
                decompressAndHash(
                    &self.mode_specific.stream_decompressor,
                    &self.mode_specific.data_item_hasher,
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
                    &self.mode_specific.stream_decompressor,
                    &self.mode_specific.data_item_hasher,
                    &self.file_name_buf,
                    data_item_buf[2..4],
                );
                self.mode_specific.streaming_contents_mode = switch (item.file_type) {
                    .file, .posix_executable => .start,
                    .directory => .directory,
                    .symlink => .symlink,
                };

                return item;
            } else {
                // IndexItem
                var index_item_buf: [22]u8 = undefined;
                decompressAndHash(
                    &self.mode_specific.index_decompressor,
                    &self.mode_specific.index_hasher,
                    &index_item_buf,
                ) catch |err| switch (err) {
                    error.EndOfStream => {
                        // End of the Index Region.
                        if (self.mode_specific.index_decompressor.unreadBytes() > 0) return error.MalformedInput; // Index Region compression stream overlaps ArchiveFooter.
                        if (self.mode_specific.index_hasher.final() != self.mode_specific.index_crc32) return error.MalformedInput; // index_crc32 mismatch.
                        return null;
                    },
                    else => return err,
                };
                var item = try readTypeNameSizeAndName(
                    Item,
                    &self.mode_specific.index_decompressor,
                    &self.mode_specific.index_hasher,
                    &self.file_name_buf,
                    index_item_buf[20..22],
                );
                item.jump_location = std.mem.readInt(u64, index_item_buf[0..8], .little);
                item.file_size = std.mem.readInt(u64, index_item_buf[8..16], .little);
                item.contents_crc32 = std.mem.readInt(u32, index_item_buf[16..20], .little);

                // precompute stream_start_offset and skip_bytes.
                if (item.jump_location > 0) {
                    self.mode_specific.stream_start_offset = item.jump_location;
                    self.mode_specific.skip_bytes = 0;
                } else {
                    // Skip the corresponding DataItem's fields before the contents.
                    self.mode_specific.skip_bytes += 4 + item.file_name.len;
                }
                item.stream_start_offset = self.mode_specific.stream_start_offset;
                item.skip_bytes = self.mode_specific.skip_bytes;
                // For the next item, skip the file_contents of this item.
                const chunking_overhead = 2 * (@divTrunc(item.file_size, 0xFFFF) + 1);
                self.mode_specific.skip_bytes += item.file_size + chunking_overhead;
                // Also skip the corresponding DataItem's fields after the contents.
                self.mode_specific.skip_bytes += 4;

                return item;
            }
        }

        pub fn skipItem(self: *@This()) !void {
            // If streaming
            if (switch (mode) {
                .stream, .stream_no_verify => true,
                .index_or_stream_fallback => self.mode_specific.is_stream_fallback,
                .index_or_error => false,
            }) {
                // Skip the DataItem.
                // TODO: don't put this on the stack at all. Use some kind of null writer.
                var buf: [0xffff]u8 = undefined;
                var ignore_me = std.io.fixedBufferStream(&buf);
                while (0 < try self.readItemContents(undefined, ignore_me.writer())) {
                    ignore_me.seekTo(0) catch unreachable;
                }
            } else {
                // Skip the IndexItem.
            }
        }
        pub fn readItemContents(self: *@This(), item: *const Item, writer: anytype) !usize {
            // If streaming
            if (switch (mode) {
                .stream, .stream_no_verify => true,
                .index_or_stream_fallback => self.mode_specific.is_stream_fallback,
                .index_or_error => false,
            }) {
                return self.readStreamingItemContents(writer);
            } else {
                // Jump into the Data Region.
                // TODO: what now?
                _ = item;
                @panic("TODO: open a stateful stream of the contents?");
            }
        }
        pub fn readStreamingItemContents(self: *@This(), writer: anytype) !usize {
            // Assert is streaming.
            assert(switch (mode) {
                .stream, .stream_no_verify => true,
                .index_or_stream_fallback => self.mode_specific.is_stream_fallback,
                .index_or_error => false,
            });

            // DataItem.chunk_size
            assert(self.mode_specific.streaming_contents_mode != .done); // Item is already done.
            var chunk_size_buf: [2]u8 = undefined;
            decompressAndHash(
                &self.mode_specific.stream_decompressor,
                &self.mode_specific.data_item_hasher,
                &chunk_size_buf,
            ) catch |err| switch (err) {
                error.EndOfStream => {
                    // Stream split.
                    if (self.mode_specific.streaming_contents_mode != .start) return error.MalformedInput; // Unexpected end of compression stream in Data Region.

                    // We need to salvage any overrun from the previous decompressor and carry it forward to the next.
                    // I could not find a way to do this through the public API,
                    // but it turns out that everything we need to make this possible is contained in the bits field.
                    // This works as of Zig 0.14.0.
                    const bits = self.mode_specific.stream_decompressor.bits;
                    self.mode_specific.stream_decompressor = .{ .bits = bits };

                    // Now retry the read.
                    try decompressAndHash(
                        &self.mode_specific.stream_decompressor,
                        &self.mode_specific.data_item_hasher,
                        &chunk_size_buf,
                    );
                },
                else => return err,
            };
            const chunk_size = std.mem.readInt(u16, &chunk_size_buf, .little);
            switch (self.mode_specific.streaming_contents_mode) {
                .start => {
                    self.mode_specific.streaming_contents_mode = .middle;
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
            try self.mode_specific.stream_decompressor.reader().readNoEof(chunk);
            self.mode_specific.data_item_hasher.update(chunk);
            if (mode == .stream) {
                // TODO: self.mode_specific.contents_hash.update(chunk);
            }

            // Return the chunk.
            try writer.writeAll(chunk);

            if (chunk.len == 0) {
                // DataItem.streaming_crc32
                const streaming_crc32 = try self.mode_specific.stream_decompressor.reader().readInt(u32, .little);
                if (streaming_crc32 != self.mode_specific.data_item_hasher.final()) return error.MalformedInput; // streaming_crc32 mismatch.
                self.mode_specific.streaming_contents_mode = .done;
            }

            return chunk.len;
        }
    };
}

const ArchiveFooter = packed struct {
    index_crc32: u32,
    index_location: u64,
    footer_checksum: u8,
    footer_signature: u24,
};
comptime {
    std.debug.assert(@sizeOf(ArchiveFooter) == 16);
}

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

fn readTypeNameSizeAndName(
    comptime Item: type,
    pointer_to_decompressor: anytype,
    hasher: *Crc32,
    file_name_buf: *[0x3fff]u8,
    type_and_name_size_buf: *const [2]u8,
) !Item {
    const type_and_name_size = std.mem.readInt(u16, type_and_name_size_buf, .little);
    const file_type = type_and_name_size >> 14;
    const name_size = type_and_name_size & 0x3fff;
    const file_name = file_name_buf[0..name_size];
    try decompressAndHash(pointer_to_decompressor, hasher, file_name);

    try validateFileName(file_name);

    return Item{
        .file_type = @enumFromInt(file_type),
        .file_name = file_name,
    };
}

pub fn validateFileName(file_name: []const u8) !void {
    if (file_name.len == 0) return error.MalformedInput; // file_name cannot be empty.
    // TODO: the rest of the validation.
}

fn decompressAndHash(pointer_to_decompressor: anytype, hasher: *Crc32, buf: []u8) !void {
    try pointer_to_decompressor.reader().readNoEof(buf);
    hasher.update(buf);
}

const Crc32 = std.hash.crc.Crc32IsoHdlc;

test Crc32 {
    // Make sure we're using this one:
    // https://reveng.sourceforge.io/crc-catalogue/all.htm#crc.cat.crc-32-iso-hdlc
    // check=0xcbf43926
    try std.testing.expectEqual(@as(u32, 0xcbf43926), Crc32.hash("123456789"));
}

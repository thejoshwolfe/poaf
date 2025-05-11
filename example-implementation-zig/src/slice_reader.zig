const std = @import("std");

pub fn SliceReader(comptime SeekableReader: type) type {
    return struct {
        // initialize these directly:
        source: *SeekableReader,
        start: usize,
        end: usize,

        pub const Reader = std.io.Reader(*@This(), SeekableReader.ReadError, read);

        pub fn reader(self: *@This()) Reader {
            return .{ .context = self };
        }

        pub fn read(self: *@This(), buffer: []u8) SeekableReader.ReadError!usize {
            try self.source.seekTo(self.start);
            const len = try self.source.read(buffer[0..@min(buffer.len, self.end - self.start)]);
            self.start += len;
            return len;
        }
    };
}

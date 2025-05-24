//! A reader for a range of a std.fs.File.
//! Tracks its own position and seeks just before each read.
//! The reader encounters an EOF at the end of the range.
//! Not thread safe, and not buffered.

const std = @import("std");
const File = std.fs.File;

// initialize these directly:
source: File,
start: usize,
end: usize,

pub const ReadError = File.ReadError || File.SeekError;
pub const Reader = std.io.Reader(*@This(), ReadError, read);

pub fn reader(self: *@This()) Reader {
    return .{ .context = self };
}

pub fn read(self: *@This(), buffer: []u8) ReadError!usize {
    try self.source.seekTo(self.start);
    const len = try self.source.read(buffer[0..@min(buffer.len, self.end - self.start)]);
    self.start += len;
    return len;
}

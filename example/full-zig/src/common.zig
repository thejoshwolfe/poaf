const std = @import("std");

pub const buffer_size = 0x10000;

pub const FileType = enum(u2) {
    file = 0,
    posix_executable = 1,
    directory = 2,
    symlink = 3,
};

pub fn validateFileName(file_name: []const u8) !void {
    if (file_name.len == 0) return error.MalformedInput; // file_name cannot be empty.
    // TODO: the rest of the validation.
}

pub const Crc32 = std.hash.crc.Crc32IsoHdlc;

test Crc32 {
    // Make sure we're using this one:
    // https://reveng.sourceforge.io/crc-catalogue/all.htm#crc.cat.crc-32-iso-hdlc
    // check=0xcbf43926
    try std.testing.expectEqual(@as(u32, 0xcbf43926), Crc32.hash("123456789"));
}

pub fn readTypeNameSizeAndName(
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

pub fn decompressAndHash(pointer_to_decompressor: anytype, hasher: *Crc32, buf: []u8) !void {
    try pointer_to_decompressor.reader().readNoEof(buf);
    hasher.update(buf);
}

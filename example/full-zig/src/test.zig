const std = @import("std");
const testing = std.testing;
const ArrayList = std.ArrayList;
const Allocator = std.mem.Allocator;
const ArenaAllocator = std.heap.ArenaAllocator;

const poaf = @import("poaf_lib");

const TestCase = struct {
    description: []const u8,
    group: []const u8,
    contents: SlicedHex,
    @"error": ?enum {
        ArchiveHeader,
        DataItem,
        IndexItem,
        ArchiveFooter,
    } = null,
    maybe_error: ?enum {
        extraction,
    } = null,
    items: ?[]Item = null,
};

const Item = struct {
    name: ?[]const u8 = null,
    compressed_name: ?SlicedHex = null,
    type: u2,
    contents: ?SlicedHex = null,
    compressed_contents: ?SlicedHex = null,
    symlink_target: ?[]const u8 = null,
};

const SlicedHex = struct {
    bytes: []const u8,
    pub fn jsonParse(allocator: Allocator, source: anytype, options: std.json.ParseOptions) std.json.ParseError(@TypeOf(source.*))!@This() {
        _ = options;
        if (.array_begin != try source.next()) return error.UnexpectedToken;
        var contents = ArrayList(u8).init(allocator);
        while (true) {
            switch (try source.nextAlloc(allocator, .alloc_if_needed)) {
                .string => |hex| {
                    if (hex.len & 1 != 0) return error.UnexpectedToken;
                    for (0..hex.len >> 1) |i| {
                        try contents.append(try std.fmt.parseInt(u8, hex[i << 1 .. (i + 1) << 1], 16));
                    }
                },
                .array_end => break,
                else => return error.UnexpectedToken,
            }
        }

        return .{ .bytes = contents.items };
    }
};
test "test data" {
    const data = @embedFile("test_data.json");

    var diagnostics = std.json.Diagnostics{};
    var scanner = std.json.Scanner.initCompleteInput(testing.allocator, data);
    defer scanner.deinit();
    scanner.enableDiagnostics(&diagnostics);
    const parsed = std.json.parseFromTokenSource([]const TestCase, testing.allocator, &scanner, .{}) catch |err| {
        std.log.err("{s}:{}:{}: {}", .{ "test_data.json", diagnostics.getLine(), diagnostics.getColumn(), err });
        return err;
    };
    defer parsed.deinit();

    for (parsed.value) |test_case| {
        const expect_error = test_case.@"error" != null;
        if (testOneCaseAllModes(&test_case)) {
            if (expect_error) {
                std.log.err("{s}: {s}:", .{ test_case.group, test_case.description });
                return error.ExpectedError; // Archive was accepted, but should have produced an error.
            }
        } else |err| {
            if (!expect_error) {
                std.log.err("{s}: {s}: {s}", .{ test_case.group, test_case.description, @errorName(err) });
                return err; // This error was not expected.
            }
        }
    }
}

fn testOneCaseAllModes(test_case: *const TestCase) !void {
    try testOneCaseStream(test_case);
    try testOneCaseIndex(test_case);
}
fn testOneCaseStream(test_case: *const TestCase) !void {
    var arena = ArenaAllocator.init(testing.allocator);
    defer arena.deinit();

    var fbs = std.io.fixedBufferStream(test_case.contents.bytes);
    var brs = std.io.bufferedReaderSize(poaf.buffer_size, fbs.reader().any());
    var archive = poaf.StreamReader{ .stream = &brs };
    try archive.init();
    var item_index: usize = 0;
    while (try archive.next()) |found_item| : (item_index += 1) {
        if (test_case.items == null) {
            // Going to be an error later.
            try archive.skipItem();
            continue;
        }
        if (item_index >= test_case.items.?.len) return error.TestFailed; // found too many items.
        const expected_item = test_case.items.?[item_index];

        // file_type, file_name
        try testing.expectEqual(expected_item.type, @intFromEnum(found_item.file_type));
        if (expected_item.name) |n| {
            try testing.expectEqualStrings(n, found_item.file_name);
        } else if (expected_item.compressed_name) |compressed_name| {
            try testing.expectEqualStrings(decompress(arena.allocator(), compressed_name.bytes), found_item.file_name);
        } else unreachable;

        // contents
        var contents_buf = ArrayList(u8).init(arena.allocator());
        while (0 < try archive.readItemContents(contents_buf.writer())) {}
        const found_contents = try contents_buf.toOwnedSlice();

        if (found_item.file_type == .symlink) {
            try testing.expectEqualStrings(expected_item.symlink_target.?, found_contents);
        } else if (expected_item.contents) |c| {
            try testing.expectEqualStrings(c.bytes, found_contents);
        } else if (expected_item.compressed_contents) |cc| {
            try testing.expectEqualStrings(decompress(arena.allocator(), cc.bytes), found_contents);
        } else unreachable;
    }
    if (test_case.items != null and item_index < test_case.items.?.len) return error.TestFailed; // not enough items.
}

fn testOneCaseIndex(test_case: *const TestCase) !void {
    var arena = ArenaAllocator.init(testing.allocator);
    defer arena.deinit();

    var tmp = testing.tmpDir(.{});
    defer tmp.cleanup();

    const file = try tmp.dir.createFile("archive.poaf", .{ .read = true, .exclusive = true });
    defer file.close();

    try file.writer().writeAll(test_case.contents.bytes);
    try file.seekTo(0);

    var archive = poaf.IndexReader{ .file = file };
    try archive.init();
    var item_index: usize = 0;
    while (try archive.next()) |found_item| : (item_index += 1) {
        if (test_case.items == null) {
            // Going to be an error later.
            continue;
        }
        if (item_index >= test_case.items.?.len) return error.TestFailed; // found too many items.
        const expected_item = test_case.items.?[item_index];

        // file_type, file_name
        try testing.expectEqual(expected_item.type, @intFromEnum(found_item.file_type));
        if (expected_item.name) |n| {
            try testing.expectEqualStrings(n, found_item.file_name);
        } else if (expected_item.compressed_name) |compressed_name| {
            try testing.expectEqualStrings(decompress(arena.allocator(), compressed_name.bytes), found_item.file_name);
        } else unreachable;

        // contents
        var contents_buf = ArrayList(u8).init(arena.allocator());
        while (0 < try archive.readItemContents(&found_item, contents_buf.writer())) {}
        const found_contents = try contents_buf.toOwnedSlice();

        if (found_item.file_type == .symlink) {
            try testing.expectEqualStrings(expected_item.symlink_target.?, found_contents);
        } else if (expected_item.contents) |c| {
            try testing.expectEqualStrings(c.bytes, found_contents);
        } else if (expected_item.compressed_contents) |cc| {
            try testing.expectEqualStrings(decompress(arena.allocator(), cc.bytes), found_contents);
        } else unreachable;
    }
    if (test_case.items != null and item_index < test_case.items.?.len) return error.TestFailed; // not enough items.
}

fn decompress(allocator: Allocator, buf: []const u8) []u8 {
    var input = std.io.fixedBufferStream(buf);
    var output = ArrayList(u8).init(allocator);
    std.compress.flate.decompress(input.reader(), output.writer()) catch unreachable;
    return output.toOwnedSlice() catch unreachable;
}

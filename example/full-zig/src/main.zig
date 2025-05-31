const std = @import("std");
const ArenaAllocator = std.heap.ArenaAllocator;

const lib = @import("poaf_lib");

fn usage(comptime problem: ?[]const u8, maybe_arg: ?[]const u8) noreturn {
    if (problem) |msg| {
        const stderr = std.io.getStdErr().writer();
        if (maybe_arg) |arg| {
        stderr.print("error: " ++ msg ++ "\n", .{arg}) catch {};
        } else {
        stderr.print("error: " ++ msg ++ "\n", .{}) catch {};
        }
    }

    const stdout_file = std.io.getStdOut().writer();
    var bw = std.io.bufferedWriter(stdout_file);
    const stdout = bw.writer();

    stdout.writeAll(
    \\usage:
    \\  extract: [options] archive_file.poaf -x out_dir/
    \\  list:    [options] archive_file.poaf
    \\  create:  [options] -o archive_file.poaf [inputs...] (TODO)
    \\
    \\options:
    \\  -x, --extract out_dir/
    \\        Extract the archive to the given directory.
    \\        If the directory does not exist, its immediate parent must exist.
    \\  -o, --output archive_file.poaf
    \\        TODO: creating an archive doesn't work yet.
    \\  -h, --help
    \\        Show this help and exit.
    \\
    ) catch {};

    bw.flush() catch {};

    std.process.exit(1);
}

pub fn main() !void {
    var arena = ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();

    const args = std.process.argsAlloc(arena.allocator());
    _ = args.next() orelse unreachable; // Discard argv[0].

    var archive_path: ?[]const u8 = null;
    var extract_path: ?[]const u8 = null;
    while (args.next()) |arg| {
        if (startsWith(arg, "-")) {
            if (startsWith(arg, "-h") or equals(arg, "--help")) usage(null, null);
            if (startsWith(arg, "-x") or startsWith(arg, "--extract=") or equals(arg, "--extract")) {
                if (extract_path != null) usage("-x/--extract option give multiple times", null);
                if (startsWith(arg, "-x") and arg.len > 2) {
                    extract_path = arg["-x".len..];
                } else if (startsWith(arg, "--extract=")) {
                    extract_path = arg["--extract=".len..];
                } else {
                    extract_path = arg.next() orelse usage("expected arg after {s}", arg);
                }
                continue;
            }
            usage("unrecognized arg: {s}", arg);
        } else {
            if (archive_path != null) usage("archive_file given multiple times", null);
            archive_path = arg;
        }
    }

    if (archive_path == null) usage("missing archive_path");

    // Prints to stderr (it's a shortcut based on `std.io.getStdErr()`)
    std.debug.print("All your {s} are belong to us.\n", .{"codebase"});

    // stdout is for the actual output of your application, for example if you
    // are implementing gzip, then only the compressed bytes should be sent to
    // stdout, not any debugging messages.
    const stdout_file = std.io.getStdOut().writer();
    var bw = std.io.bufferedWriter(stdout_file);
    const stdout = bw.writer();

    try stdout.print("Run `zig build test` to run the tests.\n", .{});

    try bw.flush(); // Don't forget to flush!
}

fn startsWith(a: []const u8, b: []const u8) bool {
    return std.mem.startsWith(u8, a, b);
}
fn equals(a: []const u8, b: []const u8) bool {
    return std.mem.equals(u8, a, b);
}

test {
    _ = @import("./test.zig");
}

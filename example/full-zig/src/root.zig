//! By convention, root.zig is the root source file when making a library. If
//! you are making an executable, the convention is to delete this file and
//! start with main.zig instead.

pub const IndexReader = @import("./index_reader.zig").IndexReader;
pub const StreamReader = @import("./stream_reader.zig").StreamReader;
pub const FileType = @import("./common.zig").FileType;
pub const validateFileName = @import("./common.zig").validateFileName;

pub const buffer_size = @import("./common.zig").buffer_size;

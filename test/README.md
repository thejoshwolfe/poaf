# poaf Test Data

The test data is a JSON array of objects with the following type:

```
TestCase = {
  "description": String,
  "group": String,
  "contents": SlicedHex,
  // either:
  "error": ErrorString,
  // or:
  "items": Array(Item),
  // and maybe:
  "maybe_error": MaybeErrorString,
}

SlicedHex = Array(HexString)
HexString = String // with an even number of characters in set [0-9a-f]

ErrorString = one of: "ArchiveHeader", "DataItem", "IndexItem", "ArchiveFooter"
MaybeErrorString = always: "extraction"

Item = {
  // Either:
  "name": String,
  // or:
  "compressed_name": SlicedHex,

  "type": FileType,

  // for FileType 0 and 1:
  // either:
  "contents": SlicedHex,
  // or:
  "compressed_contents": SlicedHex,
  // for FileType 3:
  "symlink_target": String,
}

FileType = one of: 0, 1, 2, 3
```

`"group"` is an informative string suggesting a grouping of the items.
All test cases with the same `"group"` are consecutive in the array of test cases.
`"description"` is a human-readable name of the test case.

`"contents"` encodes the bytes of the archive.

A `SlicedHex` value represents an array of bytes.
Because JSON strings are Unicode, and also to limit the length of lines in the JSON document,
binary arrays are encoded in hex where two characters is a byte,
and the array is split every 32 bytes (or 64 hex characters).
To decode, convert every 2 characters into a byte value and concatenate all `HexString` values in the `SlicedHex` together.

If the `"error"` field is present, then `"items"` and `"maybe_error"` are not.
This indicates that an implementation should report an error for the archive.
The `ErrorString` indicates where the error should be detected in the archive assuming a reader is streaming the archive from start to finish.
`"ArchiveHeader"` means there is something wrong with the `ArchiveHeader`.
For problems that are detectable in both the `DataItem` and `IndexItem`, such as an invalid `file_name` field,
the `ErrorString` will be `"DataItem"`.
For an inconsistency between a `DataItem` and its corresponding `IndexItem`, the `ErrorString` will be `"IndexItem"`.
`"ArchiveFooter"` means there is something wrong with one of the `ArchiveFooter` fields or with the end of the file.

If the `"error"` field is not present, then `"items"` is an array of 0 or more `Item` objects representing the items of the archive.
This means the archive is conformant to the specification.

One of either `"name"` or `"compressed_name"` are present in each `Item`.
`"name"` is the Unicode name of the item in the archive.
`"compressed_name"` is a `SlicedHex` encoding of deflate-compressed bytes representing the UTF-8 encoding of the name.
`"compressed_name"` is used when the name would be otherwise extremely long.

`"type"` is either 0, 1, 2, or 3 representing a regular file, a posix executable, an empty directory, or a symlink respectively.
Regular files and posix executables also have either a `"contents"` field or a `"compressed_contents"` field
encoding the contents of the item in `SlicedHex` form, the latter being deflate compressed.
Symlinks have a `"symlink_target"` field encoding the contents of the item as a Unicode string.
Empty directories have neither field.

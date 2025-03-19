# poaf

A pretty OK archive format.

I'm frustrated by the design of both ZIP and TAR, and I want to see how hard it is to make something better from scratch in 2025.

This archive format is trying to solve every write-once use case that other archive formats solve, including `.zip`, `.tar`, `.tar.gz`, `.a`, `.deb`, etc.
Use cases that involve making incremental modifications to an existing archive file are out of scope; I would say that's more akin to a database or file system format rather than an archive format.

This format is not necessarily recommended in a context where widespread adoption is meaningfully beneficial, as this is a new format as of 2025.
But that's how innovation works, so if you're still reading this, thanks for taking the time to check out this project!

The intended applications of this archive format are what are currently solved by ZIP and TAR:
* Packaging content for wide distribution. e.g. Making a highly compressed release tarball.
* Packaging content on the fly for download. e.g. Downloading a snapshot of a git repo as archive.
* Backing up a directory and preserving OS-specific metadata.
* Reading a compressed directory in-place. e.g. Extracting individual files from a `.jar`, `.docx`, `.apk`, etc.
* Transferring ephemeral information directly between software programs. e.g. Sending a build context to the docker daemon.

See also What's Wrong With ZIP/TAR? below.

## Terminology

An archive is a file containing multiple items.
An item has a name and contents, each a sequence of bytes, and possibly other metadata.

The items are the primary payload of the archive.
For example, an archive containing items named `README.md` and `LICENSE.md` would be typical for archiving a software project.
The contents of these items would the text of the documents.

While items typically correspond to files on a file system outside the archive, it is out of scope of this format specification to define the implementation details of how item data is provided during the creation of an archive or how it is used when reading an archive.
Instead, this format specification places constraints on what kind of information must be or can be known at certain times throughout the creation and reading of an archive while maintaining an upper bound on the required general-purpose memory.
For example, an item can be provide to the archive creation process with either known or unknown size of contents.
Another example is a reader can sometimes get a list of item names before being required to process the contents of the items.
See the Features section for more details.

The input to the process of creating an archive is a sequence of items, not necessarily all at once.
The input to the process of reading an archive is the archive.

A file is a sequence of bytes.
A byte is 8 bits.

A file can be used in one of the following modes:
* An unseekable read stream: Each byte of the file must be read once from start to finish. Once a byte has been read, it cannot be read again.
* A random-access file (for reading): Each byte can be read zero or more times in any order. The reader can seek to an arbitrary offset.
* An unseekable write stream: Each byte of the output file must be written once from start to finish. Once a byte has been written, it cannot be changed.
* A random-access file (For writing): Each byte must be written in sequence from start to finish, but a writer may seek backward and overwrite earlier bytes before resuming writing the next byte in the sequence.
* A tempfile: Sometimes used for creating an archive, effectively an unseekable write stream that is then read as an unseekable read stream once and then deleted. The worst case size of a tempfile is the eventual size of the archive; only a single tempfile can exist at once.

General-purpose memory is random-access memory used during creating or reading an archive.
General-purpose memory can always be bounded regardless of the size of the input.
A tempfile is not considered general-purpose memory by this document.

In addition to the terms defined above, this specification also refers to the following terms defined beyond the scope of this document:
CRC32, SHA-256, Deflate, UTF-8.
See References at the end of this document for links to these definitions.

TODO: cleanup inconsistency between "writing" and "creating".

## Features

This archive format supports a wide variety of constrained use cases.
Depending on the constraints, the structure of the archive and inclusion of optional features may vary.
A creator decides which optional features to include, and a reader may support or not support an archive with a given set of features.
The set of features used in an archive is encoded in the first few bytes.
See the `ArchiveHeader` documentation for full details.

The below is a list of use cases expressed as constraints on the writer or reader.
Some combinations are impossible to support, even in theory.
The matrix of combinations supported by this archive format is given further below.

Some combination of the following constraints may be placed on the writer:
* Streaming write: Creating an archive writing to a stream without seeking backward.
* No tempfile: Creating an archive without writing to and subsequently reading from a secondary tempfile.
* Unknown list of items: The creator is given one item at a time, not the full list up front. The creator must process the item's contents before being informed of the next item.
* Single-pass item contents: The creator can only process the contents of an item once. (For example if given an unseekable stream for an item's contents.)
* Unknown item sizes: The creator is given the contents of an item as a stream of unknown length.

Some combination of the following constraints may be placed on the reader:
* Streaming read: The archive file is read from a stream that does not support seeking backward. (The archive is not stored on disk.)
* Known number of items: The reader can get a list of the items in the archive, and the list includes at least the file name of each item.
* Jump to item contents: The reader can jump to an offset into the archive and find the contents of a specific item.
* Known item sizes: The reader can get the size of the item before being required to process the file contents.
* Known item checksums: The reader can get the checksums of an item before being required to process the file contents.

The below is a table of which combinations are supported, currently not supported, and theoretically impossible to ever support.
Remember that general-purpose memory must always be bounded, not depending on the input.
```
SW: Streaming write
  |NT: No tempfile
  |  |SI: Unknown list of items
  |  |  |SC: Single-pass item contents
  |  |  |  |SS: Unknown item sizes
  |  |  |  |  |SR: Streaming read
  |  |  |  |  |  |KI: Known number of items
  |  |  |  |  |  |  |JI: Jump to item contents (always requires KI and not SR)
  |  |  |  |  |  |  |  |KS: Known item sizes
  |  |  |  |  |  |  |  |  |KC: Known item checksums
SW|--|SI|SC|--|--|--|--|--|--| Always possible with this format. Items can always be added one at a time in a single pass.
--|NT|--|--|--|--|KI|--|--|--| Currently not supported with this format. The index is only ever at the end, which requires a tempfile.
--|--|--|--|--|SR|KI|--|--|--| Currently not supported with this format. The index is never at the start of the archive.
--|--|--|--|--|SR|--|--|--|KC| Currently not supported with this format. The checksums are always after the item contents.
--|--|--|--|--|--|--|JI|--|--| Impossible to seek to a specific item without a list of items (KI is missing).
--|--|--|--|--|SR|KI|JI|--|--| Impossible to seek in an unseekable archive (JI requires not SR).
--|NT|SI|--|--|--|KI|--|--|--| Impossible to collect an index of the archive's items added one at a time without using a tempfile.
SW|--|SI|--|--|SR|KI|--|--|--| Impossible to encode the list of items at the start of a streamed archive if the list is unknown.
SW|--|--|SC|SS|SR|--|--|KS|--| Impossible to encode the unknown size of an item's contents before processing its contents in a streamed archive.
SW|--|--|SC|--|SR|--|--|--|KC| Impossible to know the checksum without first processing the item contents.
```

TODO: replace `+---+` tables with commonmark `|---|` tables.

## Features (old)

* Archive an arbitrary number of file items. Each file item can have a file size up to 2^64-1 bytes.
* Several structural features, such as compression and checksums, and optionally enabled per archive. A reader knows within the first few bytes of the file whether it supports all the necessary features to read the archive.
* Extensible metadata on files and on the entire archive; only include metadata that makes sense for your use case.
* Compression is optional; when enabled, almost everything is stored compressed, but not necessarily in one contiguous stream.
* Support for streaming reading is optional; when disabled, the only metadata is in a central index.
* Support for random-access reading is optional; when disabled, the only metadata is interspersed with the file contents.

For creating an archive, even with all optional features enabled:
* Requires constant general-purpose memory, regardless of the number of input files.
* Requires a secondary buffer of metadata (the Index Region) that can either be buffered in general-purpose memory or be buffered in a temporary file that is written once and then copied to the primary output once.
* Requires knowing the (uncompressed) file sizes of each input file before processing it, i.e. no support for streaming individual input files of unknown size.

For reading an archive from a seekable file:
* Read an index of all the metadata without needing to decompress the contents of any item (the Index Region located at the end of the archive).
* Random-access seek to the contents of individual items. May require decompressing the contents of other irrelevant items first, but the amount of irrelevant data is bounded to a constant determined during the creation of the archive.

For reading an archive from an unseekable stream, or for reading the contents of every item unconditionally, such as for extracting the archive:
* Read the name, size, and some other metadata before decompressing each item (from the Data Region). Read the checksum metadata after decompressing the item.
* Either stop once you get to the Index Region, which contains strictly redundant information, or optionally validate that every byte of the Index Region (after decompression) exactly matches your expectation. Your expectation can be stored in a temporary file written once while processing the Data Region and read in parallel to reading the Index Region using constant general-purpose memory.

## Spec

All integers are unsigned and in little-endian byte order, meaning the integer 0x12345678 is encoded as the bytes 0x78 0x56 0x34 0x12.
A byte is 8 bits.

The existence, order, and size of every structure and field specified in this specification is normative.
There is never any padding or unused space between specified structures or fields.

### Structure

There are 4 regions to an archive:

1. Archive Header: Uncompressed
2. Data Region: Optionally compressed in one or more streams
3. (optional) Index Region: Optionally compressed separately in one stream
4. (optional) Archive Footer: Uncompressed

The following are some example diagrams of what archives might look like with various feature flags enabled:

```
// This example uses feature flags: Streaming, Index, Deflate
ArchiveHeader
// Data Region
Deflated stream 0 {
    ArchiveMetadata
    DataItem 0
    DataItem 1
    DataItem 2
}
Deflated stream 1 {
    DataItem 3
}
Deflated stream 2 {
    DataItem 4
    DataItem 5
    DataRegionSentinel
}
// Index Region
Deflated stream 3 {
    ArchiveMetadata
    IndexItem 0
    IndexItem 1
    IndexItem 2
    IndexItem 3  // specifies the size of Deflated stream 0
    IndexItem 4  // specifies the size of Deflated stream 1
    IndexItem 5
}
ArchiveFooter  // specifies the sum of the sizes of Deflated streams 0-2
```

TODO: the below examples are outdated
```
// This example uses feature flags: Index
ArchiveHeader
// Data Region
label0: file_contents 0
label1: file_contents 1
label2: file_contents 2
label3: file_contents 3
label4: file_contents 4
label5: file_contents 5
// Index Region
label6: ArchiveMetadata
IndexItem 0  // points to label0
IndexItem 1  // points to label1
IndexItem 2  // points to label2
IndexItem 3  // points to label3
IndexItem 4  // points to label4
IndexItem 5  // points to label5
ArchiveFooter  // points to label6
```

```
// This example uses feature flags: Streaming, Deflate
ArchiveHeader
// Data Region
Deflated {
    ArchiveMetadata
    DataItem 0
    DataItem 1
    DataItem 2
    DataItem 3
    DataItem 4
    DataItem 5
    DataRegionSentinel
}
```

#### Archive Header

The Archive Header region contains following structure once:

```
struct ArchiveHeader = {
    archive_signature:  3 bytes  // Always 0xFCF6BE i.e. 0xBE, 0xF6, 0xFC
    feature_flags:      1 byte
}
```

The bits of `feature_flags` have these meanings:
```
+-----+------+--------------------+
| Bit | Mask | Meaning            |
+-----+------+--------------------+
| 0-1 | 0x03 | Compression Method |
| 2   | 0x04 | Streaming          |
| 3   | 0x08 | Index              |
| 4   | 0x10 | CRC32              |
| 5   | 0x20 | SHA256             |
| 6-7 | 0xC0 | Reserved           |
+-----+------+--------------------+
```

Compression Method is one of these values:

```
+-------+----------+
| Value | Meaning  |
+-------+----------+
| 0     | None     |
| 1     | Deflate  |
| 2-3   | Reserved |
+-------+----------+
```

A Compression Method of None means the `compress()` and `decompress()` transform functions (referenced in later sections) are the identity function, meaning nothing is changed.
A Compression Method of Deflate means the `compress()` and `decompress()` transform functions are Deflate compress and decompress functions.

If Compression Method is None, `compression_method_supports_eof` is not set.
If Compression Method is Deflate, `compression_method_supports_eof` is set.
This is referenced later in the specification.

The Streaming and Index feature flags affected where the file metadata will appear in the archive.
See the Data Region and Index Region sections for more details.
At least one of Streaming or Index must be enabled.

The CRC32 and SHA256 feature flags affect what that the `checksums` fields in the archive will contain.
If CRC32 is enabled, `checksums` contains a 4-byte CRC32 checksum.
If SHA256 is enabled, `checksums` contains a 32-byte SHA-256 checksum.
If both are enabled, `checksums` contains both in the order listed here.
These feature flags determine `checksums_size` (referenced in later structures): either `0`, `4`, `32`, or `36`.

If a reader encounters an enabled Reserved feature flag or if the Compression Method is set to a Reserved value,
the archive MUST be rejected as not supported.
This situation indicates that a future version of this specification has added a feature not supported by the reader,
and the feature is critical to understanding the structure of the archive.

#### Data Region

The Data Region is divided up into one or more streams compressed separately from each other.
Every byte of the Data Region must be included in exactly one stream.
See Archive Header for the definition of `compress()` and `decompress()` used in this section,
and note that those functions can be the identity function if the Compression Method is None.

The first stream starts with the `ArchiveMetadata`.
Each subsequent stream, if any, starts at the start of a `DataItem`.
If the Index is disabled, there MUST be only be one stream.

If the Index is enabled, the Index Region contains `data_item_offset` fields that encode the locations of the start of each stream after the first.
The purpose of splitting the Data Region into multiple streams is to enable a reader to jump to the middle of the archive and decompress an item without needing to decompress all bytes leading up to that item.
The creator of an archive may choose to group multiple `DataItem` structures together into a single stream,
in which case some `data_item_offset` fields will be 0, which means they do not encode the location of the start of a stream.

If Compression Method is None, then a creator MUST not group multiple `DataItem` structures together into a single stream.
TODO: what if the contents is actually 0 size?

The Data Region first contains a `DataRegionArchiveMetadata` structure once:

```
alias DataRegionArchiveMetadata =
    if Streaming is enabled: ArchiveMetadata
    else: Empty

struct ArchiveMetadata = {
    archive_metadata_size:  2 bytes
    archive_metadata:       archive_metadata_size bytes
}

struct Empty = {}
```

Then the Data Region contains zero or more `DataItem` structures.
Each occurrence of this structure encodes an item in the archive:

```
alias DataItem =
    if Streaming is enabled: StreamingItem
    else: MinimalItem;

struct StreamingItem = {
    item_signature:        4 bytes  // Always 0xDCA9ACDC i.e. 0xDC 0xAC 0xA9 0xDC
    name_size:             2 bytes
    header_metadata_size:  2 bytes
    file_size:             8 bytes
    name:                  name_size bytes
    header_metadata:       header_metadata_size bytes
    file_contents:         file_size bytes
    checksums:             checksums_size bytes  // See ArchiveHeader for checksums_size
}

struct MinimalItem = {
    file_contents:  file_size bytes  // file_size can be found in the corresponding IndexItem
}
```

The `file_contents` is the file contents of the item.
The fields `name`, `header_metadata`, and `footer_metadata` are explained in their own sections below.

Then if Streaming and the Index are both enabled and `compression_method_supports_eof` is not set (see `ArchiveHeader`),
the Data Region contains the following structure once:

```
struct DataRegionSentinel = {
    item_signature:   4 bytes  // Always 0xDCA9ACDC i.e. 0xDC 0xAC 0xA9 0xDC
    zeros:           12 bytes  // Always all 0.
}
```

Note that the `DataRegionSentinel` appears to be the first 16 bytes of a `StreamingItem` with the `name_size`, `header_metadata_size`, and `file_size` fields all set to 0, but the `DataRegionSentinel` does not encode an item in the archive.
Note that a `StreamingItem.name_size` cannot be 0; see the documentation on the `name` field for more details.

#### Index Region

If the Index is not enabled (see `ArchiveHeader`), there is no Index Region.
This section describes the Index Region when the Index is enabled.

The Index Region is compressed in one stream.
The offset in the archive where the compressed Index Region starts is encoded in the Archive Footer; see below.

The Index Region contains the following structure once:

```
struct ArchiveMetadata = {
    archive_metadata_size:  2 bytes
    archive_metadata:       archive_metadata_size bytes
}
```

Then the Index Region contains the following structure zero or more times:

```
struct IndexItem = {
    checksums:             checksums_size bytes  // See ArchiveHeader for checksums_size
    previous_stream_compressed_size:  8 bytes
    name_size:             2 bytes
    header_metadata_size:  2 bytes
    file_size:             8 bytes
    name:                  name_size bytes
    header_metadata:       header_metadata_size bytes
}
```

If Streaming is enabled, the `ArchiveMetadata` in the Index Region must exactly match the `ArchiveMetadata` in the Data Region.

The number and order of `IndexItem` structs must match the number and order of `DataItem` structs in the Data Region.
All fields present in both structs (`name_size`, `header_metadata_size`, `file_size`, `name`, `header_metadata`, and `checksums`)
must exactly match between each `IndexItem` and the corresponding `DataItem`.

If `previous_stream_compressed_size` is non-zero, it means the Data Region is split into multiple streams,
and a stream with the given size in the archive (after compression) ends just before a new stream starts that starts with the `DataItem.file_contents` corresponding to this `IndexItem`.
This field exists to enable a reader to jump into the middle of the archive and decompress specific items without needing to decompress all items leading up to it.
An archive creator may set the `previous_stream_compressed_size` to 0 if there is no stream split in the corresponding `DataItem`; see Data Region for more details.

A reader can use the below pseudocode to compute the `stream_start_offset` and `skip_bytes` to jump into the middle of an archive for any item:

```
// Precompute stream_start_offset and skip_bytes for all index items:
let stream_start_offset = sizeof(ArchiveHeader) // The start of the Data Region
let skip_bytes = sizeof(DataRegionArchiveMetadata) // The first thing in the stream
for each index_item:
    // offset represents the start of the current
    if index_item.previous_stream_compressed_size > 0:
        stream_start_offset += index_item.previous_stream_compressed_size
        skip_bytes = 0
    else:
        if Streaming is enabled:
            // Skip the corresponding StreamingItem's fields before file_contents.
            skip_bytes += 16 + index_item.name_size + index_item.header_metadata_size
    index_item.stream_start_offset = stream_start_offset
    index_item.skip_bytes = skip_bytes
    // For the next item, skip the file_contents of this item.
    skip_bytes += index_item.file_size
    if Streaming is enabled:
        // Also skip the corresponding StreamingItem's fields after file_contents.
        skip_bytes += checksums_size // Determined by the ArchiveHeader.

// Jump to a specific item.
let index_item = the item to jump to.
seek to index_item.stream_start_offset in the archive file.
read and decompress until index_item.skip_bytes decompressed bytes have been read.
// The decompression stream is now positioned at the corresponding DataItem.file_contents.
```

If Compression Method is None, then the first `previous_stream_compressed_size` must be the size of the `DataRegionArchiveMetadata`, which might be 0,
and every subsequent `previous_stream_compressed_size` must be the size of the `DataItem` corresponding to the previous `IndexItem`.
Note that when Compression Method is None, `previous_stream_compressed_size` can be 0 in some cases,
but `skip_bytes` (computed by the above pseudocode) will never be greater than zero.

#### Archive Footer

If the Index is not enabled (see `ArchiveHeader`), there is no Archive Footer.
This section describes the Archive Footer when the Index is enabled.

```
struct ArchiveFooter = {
    checksums:                    checksums_size bytes  // See ArchiveHeader for checksums_size
    data_region_compressed_size:  8 bytes
    footer_signature:             4 bytes  // Always 0xCFE9EEB6 i.e. 0xB6 0xEE 0xE9 0xCF
}
```

A reader wishing to list the contents of the archive without decompressing the entire Data Region may start by seeking to the `ArchiveFooter`, and then decompress only the Index Region.
The start of the Index Region is at a byte offset equal to the size of the `ArchiveHeader` plus `data_region_compressed_size`.
As specified earlier, the end of the Index Region is the start of the `ArchiveFooter`.

The `checksums` are for the entire Index Region after decompression.

### Field details

#### `name`

The `name` field of each item has restrictions explained below.
The same name cannot appear in two different items (in one region).

The names of entries within the archive have validation rules.
TODO: document the `validate_archive_path` function.

#### `data_item_offset`

TODO

#### `archive_metadata`, `header_metadata`, `footer_metadata`

Each metadata is zero or more fields.
Each metadata item is in one of the following two structures:

```
struct Field8 = {
    tag:   1 byte
    size:  1 byte  // In the range 0-127
    data:  size bytes
}

struct Field16 = {
    size_plus_32640:  2 bytes  // In the range 32768-65535, encodes the range 128-32895
    tag:              1 bytes
    data:             (size_plus_32640 - 32640) bytes
}
```

A reader can distinguish between the two structs by first assuming it is a `Field8` and reading 2 bytes.
Let the two fields read be `tag` and `size` in that order.
If `size < 128`, then it is a `Field8`.
If `size >= 128`, then it is a `Field16` (and `size_plus_32640 = (size << 8) | tag`, and the real `tag` is the next byte).

A creator chooses which struct to write depending on the length of the `data`.
Let the length of the `data` be `l` and the tag be `tag`.
If `l < 128`, then the data layout is `Field8{ .tag = tag, .size = l, .data = data}`.
If `l >= 128`, then the data layout is `Field16{ .size_plus_32640 = l + 32640, .tag = tag, .data = data}`.

A reader must validate that the size specified by each field does not overflow the bounds of the metadata which contains it.

The meaning of `data` depends on the value of `tag`.
See the Metadata section for details.

### Metadata

Each metadata field has a `tag` and `data`.
See the documentation on `compression_metadata` for information about the encoded size of `data` and the difference between `Field8` and `Field16`.

The metadata fields must be sorted by `tag` ascending.
The order of multiple metadata fields with the same `tag` is specified for each tag value separately.

The below columns indicate: the tag value, whether the metadata field is allowed in `ArchiveMetadata`, whether the metadata field is allowed in `DataItem.metadata`/`IndexItem.metadata`, whether multiple of the same tag can appear in one metadata, and the name of the section below explaining the row in more detail.

+---------+---------+--------+--------+------+------------+
| Tag     | Archive | Header | Footer | Dupe | Meaning    |
+---------+---------+--------+--------+------+------------+
| 0-127   | Yes     | Yes    | Yes    | Yes  | Invalid    |
| 128     | No      | Yes    | No     | No   | `FileType` |
| 129     | No      | Yes    | No     | No   | `PosixAttributes` |
| 130     | No      | Yes    | No     | No   | `NtfsAttributes` |
| 131     | No      | No     | Yes    | No   | `Crc32`    |
| 132     | No      | No     | Yes    | No   | `Sha256`   |
| 133-253 | Yes     | Yes    | Yes    | Yes  | Ignored    |
| 254     | Yes     | Yes    | Yes    | Yes  | `Comment`  |
| 255     | Yes     | Yes    | Yes    | Yes  | `Padding`  |
+---------+---------+--------+--------+------+------------+

#### `FileType` (128)

The `data` is a single byte encoding one of the following file types:

+-------+------------------+
| value | Meaning          |
+-------+------------------+
| 0     | Regular file     |
| 1     | POSIX executable |
| 2     | Directory/folder |
| 3     | Symlink          |
| 4-254 | Invalid          |
| 255   | Other            |
+-------+------------------+

If this tag is missing from an item, it is equivalent to a value of 0: Regular file.
On POSIX, a value of 0 indicates the file is not executable.
On Windows, its executability is determined by the file extension.

On POSIX, a value of 1 indicates the file is executable.
On Windows, the value is never 1.

A value of 2 can be used to encode an empty directory an in archive, or can be used if more detailed metadata is also to be specified on this item (see below).
It is not necessary to add items for ancestor directories implied by the paths of other items in the archive.
A directory item must have a `file_size` of 0.

A value of 3 on a POSIX system means the item is a symlink.
The target of the symlink is the `file_contents` of this item.
TODO: validation rules.

A value of 255 means this item encodes something else not covered above, such as a hardlink, block or character device, etc.
Additional metadata can be used to specify what it is.
This is intended for backups.

#### `PosixAttributes` (129)

If this tag is present, a `FileType` (128) tag must also be present.
This tag is intended for backups.
TODO

#### `NtfsAttributes` (130)

If this tag is present, a `FileType` (128) tag must also be present.
This tag is intended for backups.
TODO

#### `Crc32` (131)

The `data` is 4 bytes encoding a CRC32 checksum.

When in an item's `footer_metadata`, it is the hash of the `file_contents`.
When in the `archive_footer_metadata`, it is the hash of the entire uncompressed Index Region,
including the `ArchiveMetadata` and every `IndexItem` struct.

#### `Sha256` (132)

The `data` is 32 bytes encoding the SHA-256 sum.

When in an item's `footer_metadata`, it is the hash of the `file_contents`.
When in the `archive_footer_metadata`, it is the hash of the entire uncompressed Index Region,
including the `ArchiveMetadata` and every `IndexItem` struct.

#### `Comment` (254)

The `data` is a UTF-8 encoded string comment.

This is intended for unstructured information for humans rather than machine-parsable data.
If an implementation wishes to encode structured metadata in the archive, see the Ignored section below.

If duplicates appear of this tag, the encoded comments are considered multiple sequential comments for the same item.
A renderer might present them separated by two newlines perhaps.

#### `Padding` (255)

Every byte of `data` is 0.

A creator should include this field in order to waste space, for whatever reason.

A reader should either require the data be all 0 or simply ignore the field.

#### Invalid

A creator must not include an invalid tag value.
If a reader encounters an invalid tag value, it must reject the archive as unreadable.

An invalid tag value likely means that a future version of this archive format has introduced a tag that changes the interpretation of the structure of the archive.
It is not possible to read the archive without understanding how to handle the new tag value.

#### Ignored

A creator should not include ignored tag values.
A reader should ignore ignored tag values.

An ignored tag value likely means that a future version of this archive format has introduced a tag that does not change the interpretation of the structure of the archive.
It is possible to read the archive while simply ignoring the tag value.

An implementation of this format may use an ignored tag value for custom metadata, but please also report the use case to the maintainer of this specification.
If it's a widely-applicable use case, it should be added to the official specification.
If it's a niche use case, it should be reserved in the specification so other implementations don't collide.


## What's Wrong With ZIP/TAR?

Many of the problems with ZIP and TAR can be excused due to how old the formats are (1989 and 1979 respectively).
The format's adequate feature set and long tenure has led to widespread adoption, but it's not without drawbacks.
There is still plenty of room for innovation in this space.

One area of deficiency is the supported use case constraints for creating and reading archives.
For example, neither ZIP nor TAR supports streaming an archive where the size of an item is unknown before beginning to stream it.
(ZIP General Purpose Bit 3 doesn't count, because it's design is incorrect, and consequently it's not widely supported.)
While TAR supports streaming items one at a time, it does not support a central index, which is often desired in modern contexts, such as in `.deb` archives which use a combination of two `.tar` files in a `.a` archive, where the first TAR contains a file that lists the files in the second `.tar`.

#### General problems

ZIP files do not compress metadata, have a confusing specification (I'm working on it), and have an inherently insecure structure format.
ZIP files sort of can't be read in a streaming way sometimes.
More details on all of this to come in a future blog post.

TAR files have a flagrant disregard for space efficiency
(historically motivated by hardware limitations and robustness concerns when writing to tape drives).
The TAR file format has a confusing spec, and the authors have even deprecated it in favor of the newer pax format, which never caught on.

#### Use case problems:

TAR+Compression (e.g. `.tar.gz`) files cannot be accessed in a random-access pattern, jumping to specific files or listing the contents, without decompressing the entire archive.
This makes it unsuitable for .jar and other formats that need to access an archive more like a directory on a file system.

Creating a ZIP file requires knowing the compressed and uncompressed size of each item before writing it to the archive, which means making a copy of the compressed contents in a temp file (or in memory) or seeking backward in the archive output file.
Technically you can avoid specifying the sizes by using general purpose bit 3, but that causes other problems.

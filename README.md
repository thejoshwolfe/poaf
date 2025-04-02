# poaf

A pretty OK archive format.

I'm frustrated by the design of both ZIP and TAR, and I want to see how hard it is to make something better from scratch in 2025.

This archive format is trying to solve every write-once use case that other archive formats solve, including `.zip`, `.tar`, `.tar.gz`, `.a`, `.deb`, etc.
Use cases that involve making incremental modifications to an existing archive file are out of scope; I would say that's more akin to a database or file system format rather than an archive format.

This format is not necessarily recommended in a context where widespread adoption is meaningfully beneficial, as this is a new format as of 2025.
But that's how innovation works, so if you're still reading this, thanks for taking the time to check out this project!

Here are some things you might want to do with an archive file format that this new format is trying to do better than ZIP and TAR:
* Packaging content for wide distribution. e.g. Making a highly compressed release tarball.
* Packaging content on the fly for download. e.g. Downloading a snapshot of a git repo as an archive.
* Backing up a directory and preserving OS-specific metadata.
* Reading a compressed directory in-place. e.g. Extracting individual files from a `.jar`, `.docx`, `.apk`, etc.
* Transferring ephemeral information directly between software programs. e.g. Sending a build context to the docker daemon.

See also Vs Other Archive Formats below.

## Terminology

An archive is a file containing metadata and 0 or more items.
An item has a name and contents, each a sequence of bytes, and metadata.
Metadata is a sequence of entries, each entry containing a tag and data; see the documentation on Metadata for full details.

The items are the primary payload of the archive.
For example, an archive containing items named `README.md` and `LICENSE.md` would be typical for archiving a software project.
The contents of these items would be the text of the documents.

While items typically correspond to files on a file system outside the archive, it is out of scope of this format specification to define the implementation details of how item data is provided during the creation of an archive or how it is used when reading an archive.
Instead, this format specification places constraints on what kind of information must be or can be known at certain times throughout the creation and reading of an archive while maintaining an upper bound on the required general-purpose memory.
For example, an item can be provide to the archive creation process with either known or unknown size of contents.
Another example is a reader can sometimes get a list of item names before being required to process the contents of the items.
See the Features section for more details.

The input to the process of creating an archive is a sequence of items, not necessarily all at once.
The input to the process of reading an archive is the archive.

A file is a sequence of bytes that could be located on a storage device or could be ephemerally communicated between processes.
A byte is 8 bits.

A file can be used in one of the following modes:
* An unseekable read stream: Each byte of the file must be read once from start to finish. Once a byte has been read, it cannot be read again.
* A random-access file (for reading): Each byte can be read zero or more times in any order. The reader can seek to an arbitrary offset.
* An unseekable write stream: Each byte of the output file must be written once from start to finish. Once a byte has been written, it cannot be changed.
* A random-access file (For writing): Each byte must be written in sequence from start to finish, but a writer may seek backward and overwrite earlier bytes before resuming writing the next byte in the sequence.
* A tempfile: Sometimes used for creating an archive, effectively an unseekable write stream that is then read as an unseekable read stream once and then deleted. The worst case size of a tempfile is the eventual size of the archive; only a single tempfile can exist at once.

General-purpose memory is random-access memory used during the creation or reading of an archive.
General-purpose memory can always be bounded regardless of the size of the input.
A tempfile is not considered general-purpose memory by this document.

The computational complexity analysis in this specification (when values are "bounded") considers 16-bit sizes (up to 65535 bytes) to be negligible, and 64-bit sizes (more than 65535 bytes) to be effectively unbounded.
For example, a name with a length up to 65535 bytes effectively requires worst-case constant memory to store and is not a concern,
while file contents with a length up to 18446744073709551615 bytes effectively requires worst-case infinite memory to store which is never required.

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

The CRC32 and SHA256 feature flags affect what that the `file_contents_checksums` and `index_checksums` fields in the archive will contain.
If CRC32 is enabled, the checksums fields contain a 4-byte CRC32 checksum.
Then if SHA256 is enabled, the checksums fields contain a 32-byte SHA-256 checksum.
These feature flags determine the `checksums_size` throughout the archive: either `0`, `4`, `32`, or `36`.

If a reader encounters an enabled Reserved feature flag or if the Compression Method is set to a Reserved value,
the archive MUST be rejected as not supported.
This situation indicates that a future version of this specification has added a feature not supported by the reader,
and the feature is critical to understanding the structure of the archive.

#### Data Region

If Compression Method is not None, the Data Region is compressed in one or more distinct streams.
Every byte of the Data Region structures specified below must be included in exactly one compression stream.
The first stream starts with the `DataRegionArchiveMetadata` at the start of the Data Region,
and each subsequent stream, if any, starts at the `file_contents` of a `DataItem`.
The last compression stream ends at the end of the last structure, usually the last `DataItem`, or sometimes the `DataRegionArchiveMetadata` if there are no items, or the `DataRegionSentinel` if present.
If the Index is disabled, there MUST be only be one stream for the whole Data Region.
Note that in some cases, all the Data Region structures together comprise 0 bytes of data,
but the Data Region must still be compressed if Compression Method is not None.

If Compression Method is None, the Data Region is not compressed; there are no compression streams.

Note that if the Index is enabled, each `IndexItem` contains a `previous_stream_compressed_size` field that can encode the location of the `file_contents` of the corresponding `DataItem`.
The purpose of this field is to enable a reader to first read the Index Region, then jump to the middle of the archive and read a given item's `file_contents` in bounded time (not dependent on the sizes of the prior items).
Note that the `previous_stream_compressed_size` does not encode an absolute offset, but rather a relative offset from a previous reference; see the Index Region documentation for full details.

If Compression Method is None, then every `IndexItem.previous_stream_compressed_size` must encode the location of the corresponding `DataItem.file_contents`.
Again see the Index Region documentation for full details.

If Compression Method is not None, then the creator of an archive may choose to group multiple items' `file_contents` (and any `DataItem` fields in between) together in a compression stream,
in which case it is not possible to jump to the start every item's compressed `file_contents`,
because compression streams must be decoded linearly from the start of the stream.
If a compression stream does not begin at a `DataItem.file_contents`, then the corresponding `IndexItem.previous_stream_compressed_size` must be 0, indicating an unspecified value.
(Note that when Compression Method is None, a 0 is a valid value, not an unspecified value.)
If an item's `file_size` is 0, the `previous_stream_compressed_size` MUST also be 0;
this is to avoid a structural ambiguity in the archive, and it would never be useful to jump to a zero-sized `file_contents` anyway.
Otherwise, if a compression stream begins at a `DataItem.file_contents`, then the corresponding `IndexItem.previous_stream_compressed_size` must not be 0.

The Data Region first contains a `DataRegionArchiveMetadata` structure once.
(As a reminder, if Compression Method is not None, then this and the following structures are inside one or more compressed streams.)

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
Each occurrence of this structure corresponds to an item in the archive:

```
alias DataItem =
    if Streaming is enabled: StreamingItem
    else: MinimalItem;

struct StreamingItem = {
    item_signature:           4 bytes  // Always 0xDCA9ACDC i.e. 0xDC 0xAC 0xA9 0xDC
    name_size:                2 bytes
    item_metadata_size:       2 bytes
    file_size:                8 bytes
    name:                     name_size bytes
    item_metadata:            item_metadata_size bytes
    file_contents:            file_size bytes
    file_contents_checksums:  checksums_size bytes  // See ArchiveHeader for checksums_size
}

struct MinimalItem = {
    file_contents:  file_size bytes  // file_size can be found in the corresponding IndexItem
}
```

The creator of an archive MUST set the `item_signature` appropriately.
Note that a reader CAN ignore the `item_signature`; checking the `item_signature` is never necessary for parsing the structure of the archive.
However, a reader SHOULD validate the `item_signature` to guard against implementation errors.

The `file_contents` is the file contents of the item.
The `file_contents_checksums` are for the `file_contents` (after decompression if any).
For details on the fields `name`, `item_metadata`, and `file_contents_checksums`, see their dedicated sections below.

Then if Streaming is enabled and the Index is enabled and `compression_method_supports_eof` is not set (see `ArchiveHeader`),
the Data Region contains the following structure once:

```
struct DataRegionSentinel = {
    item_signature:   4 bytes  // Always 0xDCA9ACDC i.e. 0xDC 0xAC 0xA9 0xDC
    zeros:           12 bytes  // Always all 0.
}
```

Note that the `DataRegionSentinel` appears to be the first 16 bytes of a `StreamingItem` with the `name_size`, `item_metadata_size`, and `file_size` fields all set to 0, but the `DataRegionSentinel` does not encode an item in the archive.
Note that a `StreamingItem.name_size` cannot be 0; see the documentation on the `name` field for more details.

#### Index Region

If the Index is not enabled (see `ArchiveHeader`), there is no Index Region.
This section describes the Index Region when the Index is enabled.

If Compression Method is not None, all the below structures of the Index Region are compressed together in one stream.
The location of the start of the compression stream is encoded in the Archive Footer; see below.
If Compression Method is None, the Index Region is not compressed, and the location of the start of the Index Region is encoded in the Archive Footer.

In some cases, all the Index Region structures together comprise 0 bytes of data.
In this case, if Compression Method is None, the location of the start of the Index Region is the same as the location of the start of the Archive Footer.
Or if Compression Method is not None, the Index Region is a compression stream encoding 0 bytes of data.

The Index Region contains the following structure once.
(As a reminder, if Compression Method is not None, then this and the following structure are inside a compressed stream.)

```
struct ArchiveMetadata = {
    archive_metadata_size:  2 bytes
    archive_metadata:       archive_metadata_size bytes
}
```

Then the Index Region contains the following structure zero or more times:

```
struct IndexItem = {
    file_contents_checksums:          checksums_size bytes  // See ArchiveHeader for checksums_size
    previous_stream_compressed_size:  8 bytes
    name_size:                        2 bytes
    item_metadata_size:               2 bytes
    file_size:                        8 bytes
    name:                             name_size bytes
    item_metadata:                    item_metadata_size bytes
}
```

If Streaming is enabled, the `ArchiveMetadata` in the Index Region must exactly match the `ArchiveMetadata` in the Data Region.
See the documentation on `archive_metadata` for details.

The number and order of `IndexItem` structs must match the number and order of `DataItem` structs in the Data Region.
If Streaming is enabled, all fields present in both structs (`name_size`, `item_metadata_size`, `file_size`, `name`, `item_metadata`, and `file_contents_checksums`)
must exactly match between each `IndexItem` and the corresponding `StreamingItem`.

The `previous_stream_compressed_size` field can sometimes enable a reader to jump into the middle of the archive and read the item's `file_contents` without needing to read the entire Data Region up to that point.
However, sometimes jumping to a specific item's `file_contents` is not possible, in which case the `previous_stream_compressed_size` will be 0.
Which items have non-zero `previous_stream_compressed_size` values is up to the discretion of the archive creator.

If Compression Method is None, then every item's `previous_stream_compressed_size` can be used to locate that item's `file_contents` in the Data Region using the pseudocode below unless the item's `file_size` is 0, in which case the `previous_stream_compressed_size` must be 0.
Note that it would never be useful to locate a 0-sized `file_size` in the Data Region.

If Compression Method is not None, then each `previous_stream_compressed_size` can be 0, which means an unspecified value, or non-zero, which means a compression stream starts at the corresponding `file_contents` in the Data Region.
The start of every compression stream after the first one in the Data Region must correspond to a non-zero `previous_stream_compressed_size` value in the Index Region.
A compression stream must not start at a 0-size `file_contents`, which means every item with a `file_size` of 0 must also have a `previous_stream_compressed_size` of 0;
this is to prevent ambiguity in the structure of the archive and it would never be useful to locate a 0-sized `file_size` anyway.

A reader can effectively use the below pseudocode to compute the `stream_start_offset` and `skip_bytes` to jump into the middle of an archive for any item:

```
// Precompute stream_start_offset and skip_bytes for all index items:
let stream_start_offset = sizeof(ArchiveHeader) // The start of the Data Region
let skip_bytes = sizeof(DataRegionArchiveMetadata) // The first thing in the stream
for each index_item:
    if index_item.previous_stream_compressed_size > 0:
        stream_start_offset += index_item.previous_stream_compressed_size
        skip_bytes = 0
    else:
        if Streaming is enabled:
            // Skip the corresponding StreamingItem's fields before file_contents.
            skip_bytes += 16 + index_item.name_size + index_item.item_metadata_size
    index_item.stream_start_offset = stream_start_offset
    index_item.skip_bytes = skip_bytes
    // For the next item, skip the file_contents of this item.
    skip_bytes += index_item.file_size
    if Streaming is enabled:
        // Also skip the corresponding StreamingItem's fields after file_contents.
        skip_bytes += checksums_size // Determined by the ArchiveHeader.

// Jump to a specific item.
let index_item = the item to jump to.
if Compression Method is None:
    assert index_item.skip_bytes == 0
    seek to index_item.stream_start_offset
    // The next index_item.file_size bytes are the DataItem.file_contents.
else:
    seek to index_item.stream_start_offset in the archive file.
    read and decompress until index_item.skip_bytes decompressed bytes have been read.
    // The next index_item.file_size bytes read from the decompression stream are the DataItem.file_contents.
```

#### Archive Footer

If the Index is not enabled (see `ArchiveHeader`), there is no Archive Footer.
This section describes the Archive Footer when the Index is enabled.

```
struct ArchiveFooter = {
    index_checksums:              checksums_size bytes  // See ArchiveHeader for checksums_size
    data_region_compressed_size:  8 bytes
    footer_signature:             4 bytes  // Always 0xCFE9EEB6 i.e. 0xB6 0xEE 0xE9 0xCF
}
```

A reader wishing to list the contents of the archive without decompressing the entire Data Region may start by seeking to the `ArchiveFooter`, and then decompress only the Index Region.
The start of the Index Region is at a byte offset equal to the size of the `ArchiveHeader` plus `data_region_compressed_size`.
As specified earlier, the end of the Index Region is the start of the `ArchiveFooter`.

The `index_checksums` are for the entire Index Region after decompression if any.
See the documentation for the `index_checksums` field for more details.

### Field details

#### `name`

The `name` field of each item has restrictions explained below.
The same name cannot appear in two different items (in one region).

The names of entries within the archive have validation rules.
TODO: document the `validate_archive_path` function.

#### `archive_metadata`, `item_metadata`

Each metadata is zero or more entries.
Each metadata entry is in one of the following two structures:

```
struct Entry8 = {
    tag:   1 byte
    size:  1 byte  // In the range 0-127
    data:  size bytes
}

struct Entry16 = {
    size_plus_32640:  2 bytes  // In the range 32768-65535, encodes the range 128-32895
    tag:              1 bytes
    data:             (size_plus_32640 - 32640) bytes
}
```

A reader can distinguish between the two structs by first assuming it is a `Entry8` and reading 2 bytes.
Let the two bytes read be `tag` and `size` in that order.
If `size < 128`, then it is a `Entry8`.
If `size >= 128`, then it is a `Entry16` (and `size_plus_32640 = (size << 8) | tag`, and the real `tag` is the next byte).

A creator chooses which struct to write depending on the length of the `data`.
Let the length of the `data` be `l` and the tag be `tag`.
If `l < 128`, then the data layout is `Entry8{ .tag = tag, .size = l, .data = data}`.
If `l >= 128`, then the data layout is `Entry16{ .size_plus_32640 = l + 32640, .tag = tag, .data = data}`.

A reader must validate that the size specified by each entry does not overflow the bounds of the metadata which contains it.

The meaning of `data` depends on the value of `tag`.
See the Metadata section for details.

#### `file_contents_checksums`, `index_checksums`

See the `ArchiveHeader` for what this field contains.
It will contain some combination of checksums or nothing.

The checksums are encoded in binary, not in hexadecimal.
The CRC32 value is stored in little-endian byte order.
The SHA-256 value is stored in the byte order specified by that hash function.

### Metadata

Each metadata entry has a `tag` and `data`.
See the documentation on `archive_metadata` and `item_metadata` for information about the encoded size of `data` and the difference between `Entry8` and `Entry16`.

The metadata entries must be sorted by `tag` ascending.
The order of multiple metadata entries with the same `tag` is specified for each tag value separately.

The below columns indicate: the tag value, whether the entry is allowed in `archive_metadata`, whether the metadata field is allowed in `item_metadata`, whether multiple of the same tag can appear in one metadata, and the name of the section below explaining the entry in more detail.

| Tag     | Archive | Item | Dupe | Meaning    |
|---------|---------|------|------|------------|
| 0       | No      | No   | No   | `FileType` |
| 1-127   | Yes     | Yes  | -    | Reserved   |
| 128     | No      | No   | No   | `PosixAttributes` |
| 129     | No      | No   | No   | `NtfsAttributes` |
| 130-253 | Yes     | Yes  | Yes  | Ignored    |
| 254     | Yes     | Yes  | Yes  | `Comment`  |
| 255     | Yes     | Yes  | Yes  | `Padding`  |

#### `FileType` (0)

The `data` is a single byte encoding one of the following file types:

| value | Meaning          |
|-------|------------------|
| 0     | Regular file     |
| 1     | POSIX executable |
| 2     | Directory/folder |
| 3     | Symlink          |
| 4-254 | Reserved         |
| 255   | Other            |

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

A reader must support values 0 and 2: Regular file and Directory/folder.
A reader may declare other values as unsupported.
A reader may conditionally support the value 255: Other based on other metadata for this item.

A writer must not include a reserved value.
If a reader encounters a reserved value or any value the reader does not support as per the above paragraph,
the reader must reject the item as unreadable.

#### `PosixAttributes` (128)

If this tag is present, a `FileType` (128) tag must also be present.
This tag is intended for backups.
TODO

#### `NtfsAttributes` (129)

If this tag is present, a `FileType` (128) tag must also be present.
This tag is intended for backups.
TODO

#### `Comment` (254)

The `data` is a UTF-8 encoded string comment.

This is intended for unstructured information for humans rather than machine-parsable data.
If an implementation wishes to encode structured metadata in the archive, see the Ignored section below.

If duplicates appear of this tag, the encoded comments are considered multiple sequential comments for the same item.
A renderer might present them joined by two newlines perhaps.

#### `Padding` (255)

Every byte of `data` must be 0.

A creator should include this field in order to waste space, for whatever reason.
Note that certain amounts of space are tricky to waste;
the minimum amount of space to waste is 2 bytes, not 1,
and in order to waste 130 or 131 bytes, it requires two occurrences of this entry.

A reader should either require the data be all 0 or simply ignore the field.

#### Reserved

A creator must not include any reserved tag value.
If a reader encounters a reserved tag value, it must reject the item as unreadable.

A reserved tag value means that a future version of this archive format has introduced a tag that changes the interpretation of the structure of the archive,
and is not possible to read the archive without understanding how to handle the new tag value.

#### Ignored

A creator should not include ignored tag values.
A reader should ignore ignored tag values.

An ignored tag value likely means that a future version of this archive format has introduced a tag that does not change the interpretation of the structure of the archive.
It is possible to read the archive while simply ignoring the tag value.

An implementation of this format may use an ignored tag value for custom metadata, but please also report the use case to the maintainer of this specification.
If it's a widely-applicable use case, it should be added to the official specification.
If it's a niche use case, it should be reserved in the specification so other implementations don't collide.


## Vs Other Archive Formats

I have looked into the details of ZIP, TAR, RAR, and 7z and taken all the good parts of all of them.

#### ZIP

ZIP is perhaps the most problematic archive format in popular use today.
The specification, called APPNOTE, maintained by PKWARE, Inc. is the source of the format's problems.
The specification and file format have numerous serious ambiguities which lead to developer frustration,
bugs that sometimes have security implications, and disagreement over what really counts as "compliant" with the specification.
The following discussion is in reference to APPNOTE version 6.3.10 timestamped Nov 01, 2022.

[APPNOTE.txt](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) is an old document that has not been modernized since the early 1980s.
The plain text format could have been a charming stylistic curiosity if it weren't for all the other long-standing problems with the document,
which suggests the 1980s formatting is further evidence of PKWARE's unwillingness to take accountability for document's quality.

The use of ISO verbs ("SHALL", "MAY", etc.) is incorrect.
For example, `4.3.8  File data` specifies that file data "SHOULD" be placed after the local file header,
when really that's the only place for it to be, so it needn't have any ISO verb, but "SHALL" would be the appropriate one.
I believe that whoever added the ISO verbs in version 6.3.3 in 2012 thought that "SHOULD" was how you allowed for 0-length file data arguably existing or not existing based on your philosophical beliefs, which is not appropriate for a technical specification.
Other examples include `4.3.14.1`, `4.4.1.4`, and probably many more that I'm not going to bother enumerating; try reading the document yourself, and you'll see what I mean.

Another clue about the problems with APPNOTE is that it includes numerous advertisements for PKWARE proprietary technology with contact information for their sales department encouraging the reader to purchase a license.
I understand that businesses have a job to do (literally) that requires earning money, and PKWARE owns the APPNOTE document
(actually, this is legally dubious) and so it makes sense that they would serve their business interests in a document that is probably a major entrypoint for people learning that PKWARE even exists as a company.
My criticism is not with their desire to run a for-profit business; it's with how the maintainers of the document have chosen to spend their time;
they have bothered to include advertisements for proprietary technology without cleaning up the fundamental problems with the format.

And now to talk about the most fundamental problems with the format, which is that both the APPNOTE document and the format itself are ambiguous.
Ambiguity means that the same ZIP file could be read by two different ZIP readers and found to contain completely different contents.
And ambiguity in the specification means that the implementors of both readers could reasonably believe that theirs is the more compliant and correct interpretation.
Ambiguity is a serious problem, not just for bug-free usability, but for security.
If a security scanner finds that an archive contains one set of contents, and then an application finds a different set of contents, you can see how that would lead to problems.
This [actually happened in the Android operating system](https://googlesystem.blogspot.com/2013/07/the-8219321-android-bug.html),
but thankfully the problem was caught by security researchers before any known instances of the exploit affected any end user.
[Here's another long discussion](https://gynvael.coldwind.pl/?id=682) by security researcher Gynvael Coldwind of how structural ambiguities in the ZIP file format can be used to exploit naive reader implementations.

Here are some structural ambiguities in the file format. These are real bad:
* When searching for the eocdr (End of Central Directory Record), do you search backward from a minimum comment length or forward from a maximum comment length? If you find multiple signatures, is that an error, or is one of them authoritative? Can unused data be after the eocdr, which would make searching for the signature unbounded through the whole archive?
* When streaming the archive through a reader, if you encounter general purpose bit 3 and compression method 0, how do you know when the file data has ended? This is explicitly supported by the specification in `4.4.4` with the phrase "newer versions of PKZIP recognize this bit for any compression method". The data descriptor, which apparently exists to solve this problem, is identified by either a signature or a crc32 of the file data contents, but that can be maliciously inserted into the file data.
* What is the size of the data descriptor? `4.3.9.1` states "For ZIP64(tm) format archives, the compressed and uncompressed sizes are 8 bytes each.", but nowhere is a definitive definition of what a ZIP64 format archive is. ZIP64 is an extension that can be enabled on individual headers and/or at the very end of the central directory. If the central location is what makes an entire archive in ZIP64 format, then the data descriptor is useless for streaming readers, which according to my read of the specification is the entire purpose of the data descriptor. If instead a data descriptor has 8-byte sizes when the corresponding local file header has the ZIP64 extra field, then it means the writer of the archive would either have needed to know the size would exceed 4GiB, thereby defeating the purpose of general purpose bit 3, or pessimistically needed to prepare for that possibility and spend an extra 24 bytes in the local file header writing an effectively empty ZIP64 extra field. Is that pessimism really the recommendation of the specification?
* When checking for ZIP64 format at the end of the central directory, a reader must check for the Zip64 End of Central Directory Locator signature `0x07064b50` 20 bytes before the eocdr. If the signature is found, then it's the start of the Zip64 End of Central Directory Locator structure. If not, then it's probably part of the last central directory header. In Windows archives, this data is part of the NTFS timestamp extra field. This means that files archived with a particular timestamp could corrupt the archive, incorrectly signaling the presence of ZIP64 structures.

Here are some ambiguities in the specification:
* `4.3.6 Overall .ZIP file format:` gives a diagram of a zip file with no allowance for unused space or overlap between structures. This diagram is the most eye-catching first-impression that someone is likely to notice in the document. However, this diagram contradicts other claims made in `4.1.9` stating that a ZIP file may be a self-extracting archive; no discussion is given about the implications of self-extraction capabilities on the structure of the archive, but it means that there must be space at the start of the file that is not included in the archive.
* `4.3.1` states 'A ZIP file MUST have only one "end of central directory record".', but does not elaborate on what that means. This is likely an attempt to resolve ambiguities when searching backwards for the structure, but several critical details are left unspecified, such as whether simply the 4-byte signature is what must occur only once, or whether it must occur only within the last 64k of the archive where an eocdr could reasonably be found, or whether any ambiguity should be resolved by using the last one found, or what. This leads me to believe that whoever added this clause in version 6.3.3 in 2012 did not understand the problem with eocdr search ambiguity.
* `4.3.1` states "Files MAY be added or replaced within a ZIP file, or deleted.", but this is never elaborated on. These operations are irrelevant for a file format specification; they are more applicable to software that operates on archives. One might read into the claim that unused space may be left in various places throughout the format, but that's never explicitly stated, and there are no stated bounds on where the unused space can be. For example, can there be unused space between central director headers? Unused space at the end of extra field records is intentionally inserted by the Android development tool [zipalign](https://developer.android.com/tools/zipalign); is that supposed to be allowed?
* It is unclear whether small values overridden by ZIP64 extended values must be `-1` i.e. `0xFFFF`, `0xFFFFFF`. This happens in sections `4.4.{8,9,13,16,19,20,21,22,23,24}`. Each of these sections states "If an archive is in ZIP64 format and the value in this field is [-1], the size will be in the corresponding [larger] zip64 end of central directory field.". So if a reader encounters an archive in ZIP64 format and a value is not `-1`, should it still be overridden by the ZIP64 values? Are `-1` values necessary to appear before checking for the ZIP64 format (which can cause ambiguity as stated above)?
* Generally nobody cares about multi-disk support, but `4.4.19 number of this disk` is specified wrong. It states that it's the disk number "which contains central directory end record", which is not a phrase used elsewhere and it's not clear whether that refers to the "end of central directory record" or the "zip64 end of central directory record", which can be on different disks. If each field refers to the struct that contains the field, as the name itself suggests, then one doesn't override the other, because they represent different values. Really, the 16-bit "number of this disk" field is overridden by the 32-bit "total number of disks" field, which encodes the same value but plus 1. Good luck implementing support for more than 65535 disks.
* Speaking of unclear names, APPNOTE can't seem to decide on what to call different structures and fields. The terms "directory" and "dir" seem to be used interchangeably to refer to the same thing. The "End of central directory record" contains an "end of central dir signature", and the field "total number of entries in the central directory on this disk" is sometimes referred to as "total number of entries in the central dir on this disk".
* The character encoding for file names and comments was undefined until APPNOTE 6.3.0 in 2006, where the default character encoding is defined to be "IBM Code Page 437". There are two conflicting definitions of this code page for values in the range 1-31. IBM defines the characters to be various dingbats, whereas Unicode defines the characters to be ASCII control characters with the same name. Info-ZIP uses the Unicode definition.

Here are some other minor criticisms of the ZIP file format. If ZIP files weren't so problematic, these would be the comparison points you'd like to see in some kind of concise table.
* Compression and checksums only cover file contents, not file metadata.
* The structure of an archive is so unconstrained that regions of the archive could be encoded out of order or even overlapping one another. This leads to exploits like the [zip bomb technique used by David Fifield](https://www.bamsoftware.com/hacks/zipbomb/) for extreme compression, which can be a security concern.


One area of deficiency is the supported use case constraints for creating and reading archives.
For example, neither ZIP nor TAR supports streaming an archive where the size of an item is unknown before beginning to stream it.
(ZIP General Purpose Bit 3 doesn't count, because it's design is incorrect, and consequently it's not widely supported.)
While TAR supports streaming items one at a time, it does not support a central index, which is often desired in modern contexts, such as in `.deb` archives which use a combination of two `.tar` files in a `.a` archive, where the first TAR contains a file that lists the files in the second `.tar`.

TODO: research `.rar` and `.7z` formats.

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

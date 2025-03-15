# cimabafiaw

Can I make a better archive format in a weekend?

I'm frustrated by the design of both ZIP and TAR, and I want to see how hard it is to make something better.
I'm giving myself 1 weekend (until I edit this restriction) to see how far I can get.

This archive format is trying to solve every use case that ZIP, TAR, and TAR+Compression (`.tar.gz` for example) solve in a modern context:
* Packaging content for wide distribution. e.g. Making a highly compressed release tarball.
* Packaging content on the fly for download. e.g. Download git repo as archive.
* Backing up a directory and preserving extended metadata. e.g. The "System" attribute on Windows.
* Reading a compressed directory in-place. e.g. .jar, .docx, .apk.
* Transferring ephemeral information directly between software programs. e.g. Docker context transfer.

See also What's Wrong With ZIP/TAR? below.

## Overall layout

```
+----------------+
| Archive Header | - small
+----------------+
|   Data Region  | - the bulk of the data
+----------------+
|  Index Region  | - to support random access seeking and listing
+----------------+
| Archive Footer | - small
+----------------+
```

See Spec below for more details.

## Features

* Archive an arbitrary number of file items.
* Each file item can have a file size up to 2^64-1 bytes.
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

All integers are in little-endian byte order, meaning the integer 0x12345678 is encoded as the bytes 0x78 0x56 0x34 0x12.

The existence, order, and size of every structure and field specified in this specification is normative.
There is never any padding or unused space between specified structures or fields.

### Structure

There are 4 regions to an archive:

1. Archive Header: Uncompressed
2. Data Region: Compressed in one or more streams
3. (optional) Index Region: Compressed separately in one stream
4. (optional) Archive Footer: Uncompressed

An example digram of an archive might look like this:

```
ArchiveHeader  // This example uses format 0xF1FCF6BE
// Data Region
Deflated {
    ArchiveMetadata
    DataItem 0
    DataItem 1
    DataItem 2
}
label1: Deflated {
    DataItem 3
}
label2: Deflated {
    DataItem 4
    DataItem 5
    DataRegionSentinel
}
// Index Region
label3: Deflated {
    ArchiveMetadata
    IndexItem 0
    IndexItem 1
    IndexItem 2
    IndexItem 3  // points to label1
    IndexItem 4  // points to label2
    IndexItem 5
}
ArchiveFooter  // points to label3
```

Another example might look like this:

```
ArchiveHeader  // This example uses format 0xD0FCF6BE
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

Another example might look like this:

```
ArchiveHeader  // This example uses format 0xE1FCF6BE
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

The following structure once:

```
struct ArchiveHeader = {
    archive_magic_number:  4 bytes
};
```

The first 3 bytes of the `archive_magic_number` are always 0xBE 0xF6 0xFC (mask 0x00FFFFFF equals 0x00FCF6BE).

Bits 6-7 of the last byte (mask 0xC0000000) are always set.

Bits 4-5 of the last byte (mask 0x30000000) encodes the which optional structures are present:
* 0x10000000 - Streaming is not supported. Index is present.
* 0x20000000 - Streaming is supported. Index not is present.
* 0x30000000 - Streaming is supported. Index is present.

Bits 0-3 of the last byte (mask 0x0F000000) encodes the compression method:
* 0x00000000 - None
* 0x01000000 - Deflate

Every valid combination of the above produces these magic numbers for this archive format:

+--------------+---------------+-------------+--------------------+
| Magic Number | Streaming     | Index       | Compression Method |
+--------------+---------------+-------------+--------------------+
| 0xD0FCF6BE   | Not supported | Present     | None               |
| 0xE0FCF6BE   | Supported     | Not present | None               |
| 0xF0FCF6BE   | Supported     | Present     | None               |
| 0xD1FCF6BE   | Not supported | Present     | Deflate            |
| 0xE1FCF6BE   | Supported     | Not present | Deflate            |
| 0xF1FCF6BE   | Supported     | Present     | Deflate            |
+--------------+---------------+-------------+--------------------+

#### Data Region

If the compression method is not None, the Data Region is compressed in one or more streams.
Every byte of the Data Region must be included in exactly one compression stream.
Each compression stream must begin either at the start of the Data Region (the `ArchiveMetadata.archive_metadata_size`),
or at the start of an item;
if streaming is supported, the start of an item is a `DataItem` (a `DataItem.item_magic_number`),
otherwise it is the first byte of the item's file contents.

If the index is present and the compression method is not None,
For each data item at the start of a compression stream, the corresponding `IndexItem.data_item_offset` must be non-zero.
If the compression method is None, then every data item is considered at the start of a compression stream.


The Data Region first contains the following structure once:

```
struct ArchiveMetadata = {
    archive_metadata_size:  2 bytes
    archive_metadata:       archive_metadata_size bytes
};
```

Then the Data Region contains zero or more of the following structure.
Each occurrence of this structure encodes an item in the archive:

```
struct DataItem = {
    item_magic_number:     4 bytes  // Always 0xDCA9ACDC i.e. 0xDC 0xAC 0xA9 0xDC
    name_size:             2 bytes
    header_metadata_size:  2 bytes
    file_size:             8 bytes
    footer_metadata_size:  1 byte
    name:                  name_size bytes
    header_metadata:       header_metadata_size bytes
    file_contents:         file_size bytes
    footer_metadata:       footer_metadata_size bytes
};
```

The `file_contents` is the file contents of the item.
The fields `name`, `header_metadata`, and `footer_metadata` are explained in their own sections below.

Then the Data Region contains the following structure once:

```
struct DataRegionSentinel = {
    item_magic_number:  4 bytes  // Always 0xDCA9ACDC i.e. 0xDC 0xAC 0xA9 0xDC
    zeros:             13 bytes  // Always all 0.
};
```

Note that the `DataRegionSentinel` appears to be the first 17 bytes of a `DataItem` with the `name_size`, `header_metadata_size`, `file_size`, and `footer_metadata_size` fields all set to 0, but the `DataRegionSentinel` does not encode an item in the archive.

#### Index Region

The Index Region is compressed in one stream.
The offset in the archive where the compressed Index Region starts is encoded in the Archive Footer; see below.

The Index Region contains the following structure once:

```
struct ArchiveMetadata = {
    archive_metadata_size:  2 bytes
    archive_metadata:       archive_metadata_size bytes
};
```

Then the Index Region contains the following structure zero or more times:

```
struct IndexItem = {
    data_item_offset:      8 bytes  // sometimes zero, which means unspecified.
    name_size:             2 bytes
    header_metadata_size:  2 bytes
    file_size:             8 bytes
    footer_metadata_size:  1 byte
    name:                  name_size bytes
    header_metadata:       header_metadata_size bytes
    footer_metadata:       footer_metadata_size bytes
};
```

The `ArchiveMetadata` in the Index Region must exactly match the `ArchiveMetadata` in the Data Region.

The number and order of `IndexItem` structs must match the number and order of `DataItem` structs in the Data Region.
All fields present in both structs (`name_size`, `header_metadata_size`, `file_size`, `footer_metadata_size`, `name`, `header_metadata`, and `footer_metadata`)
must exactly match between each `IndexItem` and the corresponding `DataItem`.

The `data_item_offset` of an `IndexItem` is either 0 or the offset in the archive where the compression stream starts that starts with the corresponding `DataItem`.
If the compression method is 0, then every `data_item_offset` must be non-zero and encodes the offset in the archive of the corresponding `DataItem`.

#### Archive Footer

```
struct ArchiveFooter = {
    index_region_offset:        8 bytes
    footer_magic_number:        4 bytes - Always 0xCFE9EEB6 i.e. 0xB6 0xEE 0xE9 0xCF
};
```

A reader wishing to list the contents of the archive without decompressing the Data Region may start at the end here and decompress only the Index Region.

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
struct SmallField = {
    tag:   1 byte
    size:  1 byte  // In the range 0-127
    data:  size bytes
};

struct LargeField = {
    size_plus_32640:  2 bytes  // In the range 32768-65535, encodes the range 128-32895
    tag:              1 bytes
    data:             (size_plus_32640 - 32640) bytes
}
```

A reader can distinguish between the two structs by first assuming it is a `SmallField` and reading 2 bytes.
Let the two fields read be `tag` and `size` in that order.
If `size < 128`, then it is a `SmallField`.
If `size >= 128`, then it is a `LargeField` (and `size_plus_32640 = (size << 8) | tag`, and the real `tag` is the next byte).

A creator chooses which struct to write depending on the length of the `data`.
Let the length of the `data` be `l` and the tag be `tag`.
If `l < 128`, then the data layout is `SmallField{ .tag = tag, .size = l, .data = data}`.
If `l >= 128`, then the data layout is `LargeField{ .size_plus_32640 = l + 32640, .tag = tag, .data = data}`.

The meaning of `data` depends on the value of `tag`.
See the Metadata section for details.

### Metadata

Each metadata field has a `tag` and `data`.
See the documentation on `compression_metadata` for information about the encoded size of `data` and the difference between `SmallField` and `LargeField`.

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
| 131     | No      | No     | Yes    | No   | `Checksum` |
| 131-254 | Yes     | Yes    | Yes    | Yes  | Ignored    |
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

#### `Checksum` (131)

The `data` is a string identifying which hash function has been used and the hash.
Here are some examples:

* `"crc32:9ae0daaf"`
* `"sha256:ef797c8118f02dfb649607dd5d3f8c7623048c9c063d532cc95c5ed7a898a64f"`

TODO: specify this.

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

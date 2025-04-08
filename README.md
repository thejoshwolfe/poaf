# poaf

A pretty OK archive format.

Born of a frustration with ZIP and TAR, this format is an attempt to make something better from scratch in 2025.
I've found that WinRAR and 7-Zip have both made archive formats with sounder design and richer feature sets than ZIP and TAR,
but what I'm aiming for is to make a format that is simple enough to convince people to actually adopt it.
Shoutouts to this guy who thought that the ZIP file format was "simple and well-specified": https://github.com/golang/go/issues/24057#issuecomment-377430635 .
This archive format is for you.

Features:
* Streaming writing
* Streaming reading (optional)
* Random-access consolidated metadata and selective item reading (optional)
* DEFLATE compression (optional)
* CRC32 checksums (optional)
* UTF-8 for all strings
* Implicit ancestor directories and explicit empty directories
* Symlinks and posix executable bit
* Some limitations on file names to accommodate Windows
* Open specification and permissive licensing

Non-features:
* No support for compression algorithms beyond DEFLATE
* No support for checksums beyond CRC32
* No support for encryption
* No support for file metadata for backup/restore (timestamps, uig/gid, ACLs, etc.)
* No support for obscure file types (block devices, hard links, etc.)
* An archive containing duplicate file names is technically a valid archive, but extracting it will probably result in an error.
* Windows reserved file names are allowed (CON, NUL, etc.).
* This archive format is not extensible.

This document is a formal specification for the archive format.
This project also contains an example implementation in Python,
but the implementation is informative only; this document is the normative authority.

Here is a non-normative diagram of an archive file:

```
ArchiveHeader
optionally compressed {
    for each item {
        if streaming is enabled {
            StreamingHeader(item) // file type and file name
        }
        if sometimes {
            split compression stream
        }
        SometimesChunked(item.contents)
        if streaming is enabled and CRC32 is enabled {
            CRC32(StreamingHeader(item) and SometimesChunked(item.contents))
        }
    }
    if streaming is enabled and index is enabled and compression is not enabled {
        StreamingSentinel
    }
}
if index is enabled {
    optionally compressed {
        for each item {
            IndexItem(item) // location, file type, file name, crc32
        }
        if CRC32 is enabled {
            CRC32(the IndexItem list)
        }
    }
    ArchiveFooter
}
```

## General Design Discussion

This format is designed to be written once in a single-pass stream, and then read either as a stream or by random access.
Random-access reading means starting with a consolidated metadata index at the end of the archive, then seeking back to selectively read individual items contents as needed.
One of either streaming reading support or random-access reading support can be omitted from the archive to save space if the writer knows how the archive format will be read.
The set of optional features in an archive is encoded in the first 4 bytes.

This format supports compression with the DEFLATE algorithm, the same as gzip.
Metadata and contents from multiple items can be combined into a single compression stream,
resulting in compression ratios comparable to `.tar.gz` archives.
However, the writer can strategically place breaks in the compression stream to support selective reading by random access.
This gives the best of both worlds for large items and small items.

There is no support for compression algorithms beyond DEFLATE.
This archive format prioritizes ease of implementation over optimizing compression ratios,
and DEFLATE was chosen because it is the most widely implemented lossless compression algorithm in the world as of 2025;
nearly every programming language standard library supports DEFLATE compression.

This format optionally includes crc32 checksums (also widely implemented in standard libraries) to guard against subtle and accidental corruption, especially during the selective reading use case.
Note that to guard against malicious corruption, an external cryptographically secure checksum should be used on the entire archive,
which is out of scope for this specification.

There is no support for encryption; that must be done external to this archive format.
Note that the only technical advantage of having encryption built into an archive format is to support selectively reading individual items from an archive encrypted at rest.
If you always want to read the entire archive while decrypting, then the streaming reading use case works nicely within an external encryption layer.
(Note that it is generally not recommended to encrypt the contents of files before archiving them;
not only does that make compression impossible at the archive level (you could compress before encrypting I suppose.),
but it leaves archive metadata unencrypted, which is a dubious combination of secure and insecure use cases;
encrypt at your own risk.)

Use cases that involve making incremental modifications to an existing archive file, such as appending an item, are out of scope;
consider using a database or file system rather than an archive for those use cases.

## Terminology

An archive is a file containing 0 or more items.
The items are the primary payload of the archive.
For example, an archive containing items named `README.md` and `LICENSE.md` would be typical for archiving a software project.
The contents of these items would be the text of the documents.

An item has a file name, a file type, and an item contents.
A file name is a UTF-8 encoded string of bytes; see also the dedicated documentation on `file_name`.
An item contents is a sequence of bytes.
A byte is 8 bits.

A file type is an integer with one of the following values. See also the dedicated documentation on `file_type`:
* `0` - normal file
* `1` - posix executable file
* `2` - empty directory
* `3` - symlink

A file is a sequence of bytes that can be accessed in one of the following modes:
* streaming write
* streaming read
* random-access read

The input to the process of writing an archive is a stream of items, and the output is an archive file accessible for streaming writing.
There are two ways to read an archive.
The input to the process of streaming reading an archive is an archive file accessible for streaming reading, and the output is a stream of the archive's items.
The input to the process of random-access reading an archive is an archive file accessible for random-access reading, and the output is any subset of the archive's items in any order.

While the number of items in an archive, the size of the archive, and the size of each item's contents are all unbounded,
the amount of memory strictly required during any writing or reading operation is always bounded.
The computational complexity analysis in this specification (when values are "bounded") considers 16-bit sizes (up to 65535 bytes) to be negligible, and 64-bit sizes (more than 65535 bytes) to be effectively unbounded.
For example, a file name has a length up to 16383 bytes, which effectively requires worst-case constant memory to store and is not a concern,
while an item contents with a length up to 18446744073709551615 bytes effectively requires worst-case infinite memory to store which is never required.

In addition to memory, a tempfile is sometimes required during the writing process in support of random-access reading.
A tempfile is a sequence of bytes with an unbounded required size that is written once in a streaming mode, then read back once in a streaming mode.
The required size of the tempfile scales with the number of items, not any item contents.
The term tempfile is a suggestion hint for implementers, but could be implemented by an in-memory buffer at the implementer's discretion.

In addition to the terms defined above, this specification also refers to the following terms defined beyond the scope of this document:
CRC32, DEFLATE, UTF-8.
See References at the end of this document for links to these definitions.

## Spec

All integers are unsigned and in little-endian byte order, meaning the integer 0x12345678 is encoded as the bytes 0x78 0x56 0x34 0x12.
The existence, order, and size of every structure and field specified in this specification is normative.
There is never any padding or unused space between specified structures or fields.

There are 4 regions to an archive:

1. `ArchiveHeader`: Never compressed
2. Data Region: Optionally compressed in one or more streams
3. (optional) Index Region: Optionally compressed separately in one stream
4. (optional) `ArchiveFooter`: Uncompressed

A writer produces each of these sections in order.
A writer may require a tempfile to write the Index Region on the side while producing the Data Region,
then concatenate the Index Region after the Data Region is done.

A streaming reader only needs to read the `ArchiveHeader`, then the Data Region.
A random-access reader needs to read the `ArchiveHeader`, then the `ArchiveFooter`, then the Index Region,
then can read the contents of any desired item from the Data Region.

Any reader may read only part of the archive, such as streaming only the first item's contents then stopping.
If a reader does not encounter a structure documented in this specification, then the associated requirements on readers do not apply.
For example, if a reader does not encounter the `ArchiveFooter`, then the requirement to verify the `footer_checksum` does not apply to that reader.

### Regions

#### `ArchiveHeader`

The `ArchiveHeader` is the following structure:

```
struct ArchiveHeader = {
    archive_signature:           3 bytes  // Always 0xFCF6BE i.e. 0xBE, 0xF6, 0xFC
    feature_flags_and_checksum:  1 byte
}
```

The lower 4 bits of `feature_flags_and_checksum` encode the following feature flags:

| Bit | Mask | Meaning     |
|-----|------|-------------|
|   0 |    1 | Compression |
|   1 |    2 | CRC32       |
|   2 |    4 | Streaming   |
|   3 |    8 | Index       |

The upper 4 bits of `feature_flags_and_checksum` are the bitwise negation of the lower 4 bits.
For example, `0x0F` would represent a `feature_flags_and_checksum` with all features enabled,
or `0xB4` would represent only Streaming enabled.
A full `ArchiveHeader` enabling all features interpreted as a 4-byte integer would be `0x0FFCF6BE`.

A reader must verify the integrity of the `ArchiveHeader` by asserting that `archive_signature` is the expected value
and that the upper and lower halves of `feature_flags_and_checksum` are bitwise complimentary, or else reject the archive.
Then if a reader does not support the given set of features, the reader may reject the archive.
Note that if a reader does not support CRC32, that feature can easily be ignored.

If neither Streaming nor Index are enabled, then neither Compression nor CRC32 may be enabled either.
This indicates an empty archive with no items.
In this case, the entire archive is just the 4-byte integer `0xF0FCF6BE`,
and the end of the `ArchiveHeader` must be the end of the archive file.
Note that an archive may still have no items even with some other feature flags enabled.

#### Data Region

If Compression is not enabled, the Data Region is not compressed.

If Compression is enabled, the Data Region is compressed in one or more distinct streams,
and every byte of the Data Region structures specified below must be included in exactly one compression stream.
If Index is not enabled, the Data Region must not be split into more than 1 compression stream.
If the Data Region is split into multiple compression streams,
the splits must happen at the locations explained below.

The purpose of compression stream splitting is to enable random-access reading to jump into the middle of the Data Region.
It is suggested that a writer supporting this use case split the read stream at the next opportunity after the previous compressed size exceeds a threshold.
Higher thresholds result in better compression ratios, and lower thresholds result in faster random-access reading of single items.
The recommended threshold for general purpose archives is 1MiB.

Note that in some cases, all the Data Region structures together comprise 0 bytes of data,
but the Data Region must still be compressed if Compression is enabled.

If Streaming is enabled, the Data Region contains the following struct for each item:
```
struct StreamingItem = {
    // StreamingHeader:
    streaming_signature:   2 bytes   // Always 0xACDC i.e. 0xDC 0xAC
    type_and_name_size:    2 bytes   // (type_and_name_size >> 14) is the file_type
    file_name:   (type_and_name_size & 0x3FFF) bytes   // In UTF-8

    // Compression stream split may be here.

    // Chunked item contents:
    repeated: {
        chunk_size:  2 bytes
        chunk:       chunk_size bytes
    } until (chunk_size < 0xFFFF)

    // Optional checksum
    streaming_crc32:  0 or 4 bytes  // of the whole StreamingItem except for this field.
}
```
A writer of an archive must set the `streaming_signature` appropriately,
and a reader should validate the `streaming_signature` to guard against implementation errors.
Note that checking the `streaming_signature` is never necessary for parsing the structure of the archive.

The top 2 bits of `type_and_name_size` is the file type as a 2-bit integer.
The lower 14 bits of `type_and_name_size` is the length of `file_name` in bytes.
`file_name` is encoded in UTF-8 and has a maximum length of `16383`.

The item's contents is the concatenation of each `chunk`.
Before each `chunk` is a 2-byte `chunk_size` giving the length of the chunk in bytes.
If `chunk_size` is the maximum value `0xFFFF`, there is at least one more chunk.
A `chunk_size` less than `0xFFFF` indicates that this is the last `chunk`.
Note that `chunk_size` can be `0`.

If CRC32 is enabled, `streaming_crc32` is the CRC32 hash of every byte of the `StreamingItem`, after decompression if any, up but not including the `streaming_crc32` field itself.
Note that sometimes a `StreamingItem` is split between multiple compression streams.
If CRC32 is not enabled, there is no `streaming_crc32` field.

If and only if Streaming and Index are both enabled and Compression is not enabled,
the Data Region ends with the following structure once:

```
struct StreamingSentinel = {
    // StreamingHeader:
    streaming_signature:  2 bytes  // Always 0xACDC i.e. 0xDC 0xAC
    zero:                 2 bytes  // Always 0
}
```

Note that the `StreamingSentinel` appears to be the first 4 bytes of a `StreamingItem` with the `type_and_name_size` set to 0, but the `StreamingSentinel` does not encode an item in the archive.
Note that a `file_name` cannot be 0 length; see the dedicated section on the `file_name` field for more details.

If Streaming is not enabled, the Data Region contains the following for each item (instead of a `StreamingItem`):

```
struct NonStreamingDataRegionItem = {
    // Compression stream split may be here.

    contents:  file_size  bytes  // file_size can be found in the IndexItem struct.
}
```

This is simply the item's contents with no other metadata before or after.
How to parse the Data Region when Streaming is not enabled is explained in the Index Region documentation.

If Compression is enabled, the end of the Data Region is always the end of a compression stream.
A streaming reader can be sure that the end of a compression stream just before where a `streaming_signature` would be expected signals the end of the Data Region.
Note that there can be 0 occurrences of the `StreamingItem` struct in the Data Region,
but if Compression is enabled, the Data Region always contains at least 1 compression stream.

#### Index Region

If Index is not enabled, there is no Index Region.
This section describes the Index Region when Index is enabled.

If Compression is not enabled, the Index Region is not compressed.
If Compression is enabled, all the structures of the Index Region are compressed together in one compression stream.

The Index Region contains the following structure for each item:

```
struct IndexItem = {
    contents_crc32:      0 or 4 bytes
    jump_location:       8 bytes       // Can be 0 meaning unspecified
    file_size:           8 bytes
    type_and_name_size:  2 bytes
    file_name:           (type_and_name_size & 0x3FFF) bytes
}
```

The Index Region and Data Region must be generated with the same sequence of items, same number and order.
If Streaming is enabled, the fields present in both structs (`type_and_name_size` and `file_name`)
must exactly match between each `IndexItem` and the corresponding `StreamingItem`.

`file_size` is the size of the of the item's contents, after decompression if any.

If CRC32 is enabled, `contents_crc32` is the CRC32 of the contents of the item, after decompression if any, not including any `chunk_size` fields if any.
This means that if the item is extracted to a file system, `contents_crc32` is the CRC32 of the extracted file contents.
If CRC32 is not enabled, there is no `contents_crc32` field.

The `jump_location` field can sometimes enable a reader to jump into the middle of the archive and read the item's contents without needing to read the entire Data Region up to that point.
However, sometimes jumping to a specific item's contents is not possible, in which case the `jump_location` will be 0.

If Compression is not enabled, then every item's `jump_location` must be the offset from the start of the archive to one of the following:
if Streaming is enabled, the corresponding `StreamingItem`'s first `chunk_size`;
if Streaming is not enabled, the corresponding `NonStreamingDataRegionItem`'s `contents`.
If Compression is not enabled, a reader must verify that every `jump_location` is non-zero.
(As a reminder, a reader is only strictly required to verify structures that it actually encounters in the archive.)

If Compression is enabled, then every non-zero `jump_location` specifies the offset from the start of the archive to a split in the Data Region compression stream contained within the corresponding `StreamingItem` or `NonStreamingDataRegionItem`,
and every split in the Data Region compression stream must be specified by exactly one `jump_location`.

A reader must verify that every non-zero `jump_location` is less than the start of the Index Region.
A reader must also verify that each non-zero `jump_location` in the Index Region is monotonically increasing,
meaning each after the first is greater than or equal to the previous.
These checks guard against overlapping or out-of-order structures, which mitigates zip-bomb-like denial of service attacks.

Note that when an item's `file_size` is `0` and Streaming is not enabled, then some odd but still sound situations appear with the `jump_location` fields.
In this situation, when Compression is not enabled, multiple consecutive items will have the same `jump_location`;
and when Compression is enabled, a stream split could arguably be considered to be in multiple `NonStreamingDataRegionItem` structs,
however only the first of such item's `jump_location` must specifying the stream split.

In order for a random-access reader to location the contents of an arbitrary item, the following pseudocode can effectively be used to compute `stream_start_offset` and `skip_bytes` for each item:

```
// Precompute stream_start_offset and skip_bytes for all index items:
let stream_start_offset = 4 // The start of the Data Region
let skip_bytes = 0
for each index_item {
    if index_item.jump_location > 0 {
        stream_start_offset = index_item.jump_location
        skip_bytes = 0
    } else {
        if Streaming is enabled {
            // Skip the corresponding StreamingItem's fields before the contents.
            skip_bytes += 4 + index_item.name_size
        }
    }
    index_item.stream_start_offset = stream_start_offset
    index_item.skip_bytes = skip_bytes
    // For the next item, skip the file_contents of this item.
    skip_bytes += index_item.file_size
    if Streaming is enabled {
        let chunking_overhead = 2 * (floor(index_item.file_size / 0xFFFF) + 1)
        skip_bytes += chunking_overhead
        if CRC32 is enabled {
            // Also skip the corresponding StreamingItem's fields after the contents.
            skip_bytes += 4
        }
    }
}

// Jump to a specific item.
let index_item = the item to jump to.
if index_item.file_size == 0 {
    // There is no contents
    stop
}

if Compression is not enabled {
    assert index_item.skip_bytes == 0
    seek to index_item.stream_start_offset
    if Streaming is enabled {
        // What follows is the first chunk_size of the item's contents.
    } else {
        // What follows is the item's contents.
    }
} else {
    seek to index_item.stream_start_offset in the archive file.
    read and decompress until index_item.skip_bytes decompressed bytes have been read.
    if Streaming is enabled {
        // What follows in the compression stream is the first chunk_size of the item's contents.
    } else {
        // What follows in the compression stream is the item's contents.
    }
}
```

If Compression is enabled, the compressed stream ends exactly where the `ArchiveFooter` begins,
and the end of Index Region is exactly at the end of the decompressed bytes from the compression stream;
note that the Index Region can be empty, in which case the compression stream will contain `0` decompressed bytes.

If Compression is not enabled, the Index Region ends exactly where the `ArchiveFooter` begins.

#### `ArchiveFooter`

If Index is not enabled, there is no `ArchiveFooter`.
This section describes the `ArchiveFooter` when Index is enabled.

```
struct ArchiveFooter = {
    index_crc32:            0 or 4 bytes
    index_region_location:  8 bytes
    footer_checksum:        1 byte
    footer_signature:       3 bytes  // Always 0xCFE9EE i.e. 0xEE 0xE9 0xCF
}
```

A reader must verify there is no overlap between the `ArchiveFooter` and `ArchiveHeader`;
this can be done by requiring that the start of the `ArchiveFooter` is at least 4.
A reader must verify `footer_signature` to guard against corruption due to truncation.

`footer_checksum` is the lower 8 bits of the sum of each individual byte of `index_region_location`.
For example if `index_region_location` is `123456`, then `footer_checksum` is `35`.
A writer must set `index_region_location` appropriately,
and a reader must validate `index_region_location`.

`index_region_location` is the offset in the archive of the start of the Index Region.
If Compression is enabled, a compression stream begins at the given offset.

A reader must verify there is no overlap between the `ArchiveHeader`, the Index Region, and the `ArchiveFooter`.
If a reader has been streaming the archive input file, then this check is trivially already done.
A random-access reader jumping to the `ArchiveFooter` can check this with the following:
`index_region_location` must be at least `4`;
if Compression is enabled `index_region_location` must be less than the start of the `ArchiveFooter`,
otherwise it must be less than or equal to the start of the `ArchiveFooter`.
Note that ensuring no overlap between the Data Region and other regions is discussed in the Index Region documentation above.

If CRC32 is enabled, `index_crc32` is the CRC32 of the entire Index Region, after decompression if any.

The archive file must end at the end of the `ArchiveFooter`.

### `file_name`

There are some restrictions placed on `file_name` fields to mitigate compatibility issues with some environments.
However note that readers must be prepared to check for and handle problems.
Notably, duplicate file names are not inherently forbidden by this archive format,
and collisions between items are possible even when there is no obvious similarity between item names.
A writer should avoid causing name collisions,
but a reader must always guard against collisions in whatever environment the reader is operating in.

Collisions and other problems with writing a file with a given name to a file system can happen in numerous non-obvious circumstances.
On Windows and MacOS, collisions can come from case insensitivity.
On Windows certain file names are reserved such as `con.txt`.
On MacOS, file names are NFD normalized.
On most systems, there is an upper limit on the length of file paths or on file names within a file path.
These issues are beyond the scope of this technical specification,
so a reader should be prepared to check for problems due to these issues.

If items have colliding or otherwise problematic names, a reader must either trust the first matching non-problematic item or reject the archive.
Because the number of items in an archive is unbounded, there is no hard requirement to guard against name collisions for any use case.
However, during the operation of extracting an archive onto a file system, collisions can be detected by using the appropriate system call, for example:
on POSIX, `open()` with `O_CREAT|O_EXCL` flags; on Windows, `CreateFileW()` with the `CREATE_NEW` creation disposition; etc.

A reader may always reject an archive for any reason even if not explicitly permitted by this specification.

Despite the disclaimers above, this specification does impose some restrictions on the `file_name` field to mitigate common and easily avoided compatibility and security issues on some systems.

* the length of `file_name` in bytes must be at least `1` and at most `16383`.
* `file_name` must be valid UTF-8.
* `file_name` must not contain any bytes in the range `0x00` to `0x1f` (control characters) or any of the following byte values: `0x22`, `0x2a`, `0x3a`, `0x3c`, `0x3e`, `0x3f`, `0x5c`, `0x7c` (`"*:<>?\|`).

Byte value `0x2f` (`/`) is the path delimiter.
Let `segments` be the result of splitting `file_name` on `/`.

For each `segment` in `segments`:
* `segment` must not be empty.
* `segment` must not be `.` or `..` (byte value `0x2e`). (See `file_type` for how symlink targets different slightly in this rule.)

This forbids non-normalized paths and path traversal vulnerabilities.

When extracting an archive to a file system, before extracting a given item, a reader should perform the following.
For each substring `ancestor` from the start of `file_name` to just before each `/` in `file_name` in order:
* if `ancestor` does not exist in the target location, a reader should create it as a directory;
* if `ancestor` already exists, a reader should require that it is a directory, not a file or a symlink.

### `file_type`

An item's file type is encoded as a 2-bit integer:

* `0` - normal file
* `1` - posix executable file
* `2` - empty directory
* `3` - symlink

A reader may reject archives with unsupported file types.

The distinction between type `0` and `1` is that the latter should have its `chmod +x` bit set on posix systems.
Note that on Windows, executeability is generally determined by file extension, so an `.exe` file may have file type `0`.
A reader extracting an archive on a posix system with Windows executables should be prepared to handle this situation.

A file of type `2` is only necessary to include in an archive if no other item in the archive implies the need for the directory to exist as its ancestor.
See `file_name` above.
It is not possible to specify any metadata for a directory.
If `file_type` is `2`, then the item's contents must be 0-length.

A file of type `3` is a posix symlink.
The item's contents is the target.
This specification places restrictions on symlink targets, similar to restrictions on `file_name`.

All the same restrictions on `file_name` apply to symlink targets, except that `.` and `..` segments are sometimes permitted:
If the entire link target is `.`, it is permitted, otherwise `.` segments are not allowed.
Let `depth` be the number of `/` bytes in the item's `file_name`.
Let `segments` be the result of splitting the link target on `/`.
A segment may be `..` only if every prior segment, if any, is also `..`, and the total number of `..` segments does not exceed `depth`.
This is to prevent path traversal vulnerabilities.


## Rant about the problems with ZIP files

TODO: move to a blog post.

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
And ambiguity in the specification means that the implementers of both readers could reasonably believe that theirs is the more compliant and correct interpretation.
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


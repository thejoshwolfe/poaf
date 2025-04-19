
class FileSlice:
    """
    given a file-like object supporting seek(n) and read(n)
    and given a start and end position,
    this object supports read(n) through the region seeking in the file as necessary.
    """
    def __init__(self, file, start, end):
        self.file = file
        self.start = start
        self.end = end
    def read(self, n):
        n = min(n, self.end - self.start)
        if self.file.seek(self.start) != self.start:
            # Must have exceeded the EOF or something
            return b""
        buf = self.file.read(n)
        self.start += len(buf)
        return buf

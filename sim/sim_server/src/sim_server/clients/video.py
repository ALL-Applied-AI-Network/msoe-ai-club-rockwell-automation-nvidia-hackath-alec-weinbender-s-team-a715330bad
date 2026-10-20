"""Writes rendered frames to an mp4 as they arrive, so a recording never holds its frames in memory. Isaac-free.

H.264 in yuv420p, the format every browser plays, through the ffmpeg that the imageio-ffmpeg wheel bundles (the GB10 has
no system ffmpeg, and no sudo to add one). +faststart puts the index first, so a browser can start playing before the
whole file has loaded.
"""

from pathlib import Path


class Mp4Writer:
    def __init__(self, path: Path, size: tuple[int, int], fps: int):
        import imageio_ffmpeg  # only a recording needs it

        self.path, self.frames = path, 0
        self._frames = imageio_ffmpeg.write_frames(
            str(path),
            size,
            fps=fps,
            codec="libx264",
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            quality=8,
            macro_block_size=1,  # the size is checked to be even instead of letting ffmpeg resize
            output_params=["-movflags", "+faststart"],
        )
        self._frames.send(None)

    def write(self, rgb: bytes) -> None:
        """One frame: width x height x 3 bytes, RGB."""
        self._frames.send(rgb)
        self.frames += 1

    def close(self) -> None:
        self._frames.close()

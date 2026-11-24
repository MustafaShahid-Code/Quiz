"""Server-side image optimisation: orientation fix, metadata strip, downscale, recompress.

Only ever returns bytes that are valid images in a supported format. If anything goes wrong the original bytes are kept.
SVG, fonts and animated GIFs are never touched here (the caller only passes raster images)."""
from io import BytesIO

from PIL import Image, ImageOps

from . import config

RECOMPRESS_ABOVE = 600 * 1024   # re-encode photos bigger than this even when they are not too wide


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)


def optimize(data: bytes, fmt: str) -> tuple[bytes, str]:
    """-> (bytes, PIL format). fmt is the sniffed PIL format name (PNG/JPEG/WEBP/GIF)."""
    if fmt == "GIF":
        return data, fmt
    try:
        im = Image.open(BytesIO(data))
        if getattr(im, "is_animated", False):
            return data, fmt
        has_exif = bool(im.getexif())
        im = ImageOps.exif_transpose(im)   # phone photos: bake the rotation in, then drop EXIF/GPS
        w, h = im.size
        too_big = max(w, h) > config.IMAGE_MAX_PX
        if not too_big and len(data) <= RECOMPRESS_ABOVE:
            if not (fmt == "JPEG" and has_exif):
                return data, fmt   # small and clean: keep the original bytes
        if too_big:
            im.thumbnail((config.IMAGE_MAX_PX, config.IMAGE_MAX_PX), Image.LANCZOS)
        out = BytesIO()
        alpha = _has_alpha(im)
        if fmt == "PNG" and alpha:
            # logos / cut-outs keep their transparency
            im.convert("RGBA").save(out, "PNG", optimize=True); out_fmt = "PNG"
        elif fmt == "PNG" and len(data) <= RECOMPRESS_ABOVE:
            im.save(out, "PNG", optimize=True); out_fmt = "PNG"
        else:
            im.convert("RGB").save(out, "JPEG", quality=config.IMAGE_QUALITY, optimize=True, progressive=True); out_fmt = "JPEG"
        if fmt == "WEBP":
            out = BytesIO(); im.convert("RGBA" if alpha else "RGB").save(out, "WEBP", quality=config.IMAGE_QUALITY); out_fmt = "WEBP"
        res = out.getvalue()
        if len(res) >= len(data) and not too_big and not has_exif:
            return data, fmt   # never make a file bigger (unless it had to be downscaled)
        return res, out_fmt
    except Exception:
        return data, fmt

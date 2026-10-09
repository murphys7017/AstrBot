"""Validated image loading for model-provider payloads.

This module intentionally materializes media at the provider boundary instead of
mutating inbound message components.  It keeps platform URLs available to
plugins while ensuring providers receive verified image bytes.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import re
import socket
import ssl
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp
import certifi
from aiohttp.abc import AbstractResolver
from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError

from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
from astrbot.core.utils.path_util import file_uri_to_path

DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_IMAGE_TIMEOUT_SECONDS = 20
DEFAULT_PROVIDER_IMAGE_MAX_DIMENSION = 1536
DEFAULT_PROVIDER_IMAGE_JPEG_QUALITY = 82
DEFAULT_PROVIDER_IMAGE_MAX_BYTES = 512 * 1024

_FORMAT_MIME_TYPES = {
    "AVIF": "image/avif",
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


class ImageMaterializationError(ValueError):
    """The supplied image reference could not be safely materialized."""


@dataclass(frozen=True, slots=True)
class MaterializedImage:
    """Verified image bytes and the metadata required by provider adapters."""

    data: bytes
    mime_type: str
    sha256: str

    def to_data_url(self) -> str:
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"

    def prepare_for_provider(
        self,
        *,
        max_dimension: int = DEFAULT_PROVIDER_IMAGE_MAX_DIMENSION,
        jpeg_quality: int = DEFAULT_PROVIDER_IMAGE_JPEG_QUALITY,
        max_bytes: int = DEFAULT_PROVIDER_IMAGE_MAX_BYTES,
    ) -> MaterializedImage:
        """Resize and re-encode one image for a model-facing request.

        This is intentionally opt-in.  The general materializer preserves the
        original verified bytes because callers such as file tools may need
        byte fidelity.  Persona requests only need visual semantics, so they
        can use a bounded representation instead.
        """
        if max_dimension <= 0:
            raise ValueError("max_dimension must be positive")
        if not 1 <= jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 1 and 100")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        try:
            with PILImage.open(BytesIO(self.data)) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail(
                    (max_dimension, max_dimension),
                    resample=PILImage.Resampling.LANCZOS,
                )
                has_alpha = (
                    "A" in image.getbands() or "transparency" in image.info
                )
                if has_alpha:
                    output_format = "PNG"
                    output_mime = "image/png"
                    prepared = image.convert("RGBA")
                    save_kwargs = {"optimize": True}
                else:
                    output_format = "JPEG"
                    output_mime = "image/jpeg"
                    prepared = image.convert("RGB")
                    save_kwargs = {
                        "quality": jpeg_quality,
                        "optimize": True,
                        "progressive": True,
                    }

                while True:
                    buffer = BytesIO()
                    prepared.save(buffer, format=output_format, **save_kwargs)
                    data = buffer.getvalue()
                    if len(data) <= max_bytes:
                        break
                    if output_format == "JPEG" and save_kwargs["quality"] > 35:
                        save_kwargs["quality"] = max(35, save_kwargs["quality"] - 10)
                        continue
                    if prepared.size == (1, 1):
                        raise ImageMaterializationError(
                            "image cannot fit the provider size limit"
                        )
                    scale = min(0.85, (max_bytes / len(data)) ** 0.5 * 0.9)
                    width, height = prepared.size
                    prepared = prepared.resize(
                        (max(1, int(width * scale)), max(1, int(height * scale))),
                        resample=PILImage.Resampling.LANCZOS,
                    )
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            raise ImageMaterializationError(
                "image could not be prepared for provider request"
            ) from exc

        if not data:
            raise ImageMaterializationError("prepared image data is empty")
        return MaterializedImage(
            data=data,
            mime_type=output_mime,
            sha256=hashlib.sha256(data).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class _PinnedAddress:
    host: str
    family: int
    protocol: int


class _PinnedPublicResolver(AbstractResolver):
    """Resolve one approved host to the addresses checked before connection."""

    def __init__(self, host: str, addresses: tuple[_PinnedAddress, ...]) -> None:
        self._host = host.lower().rstrip(".")
        self._addresses = addresses

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_UNSPEC,
    ) -> list[dict[str, object]]:
        if host.lower().rstrip(".") != self._host:
            raise OSError("unexpected image download host")
        return [
            {
                "hostname": self._host,
                "host": address.host,
                "port": port,
                "family": address.family,
                "proto": address.protocol,
                "flags": socket.AI_NUMERICHOST,
            }
            for address in self._addresses
            if family in {socket.AF_UNSPEC, address.family}
        ]

    async def close(self) -> None:
        return None


async def materialize_image_ref(
    image_ref: str,
    *,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    timeout_seconds: float = DEFAULT_IMAGE_TIMEOUT_SECONDS,
) -> MaterializedImage:
    """Load and validate a data URL, local path, or public HTTP(S) image."""
    if not isinstance(image_ref, str) or not image_ref.strip():
        raise ImageMaterializationError("image reference is empty")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    ref = image_ref.strip()
    if ref.startswith("data:"):
        image_bytes = _decode_data_url(ref, max_bytes=max_bytes)
    elif ref.startswith("base64://"):
        image_bytes = _decode_base64(ref.removeprefix("base64://"), max_bytes=max_bytes)
    elif ref.startswith(("http://", "https://")):
        image_bytes = await _download_public_image(
            ref,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        )
    else:
        path = _resolve_trusted_local_image_path(ref)
        image_bytes = await asyncio.to_thread(_read_local_image, path, max_bytes)

    mime_type = _detect_image_mime_type(image_bytes)
    return MaterializedImage(
        data=image_bytes,
        mime_type=mime_type,
        sha256=hashlib.sha256(image_bytes).hexdigest(),
    )


def _decode_data_url(value: str, *, max_bytes: int) -> bytes:
    header, separator, payload = value.partition(",")
    if not separator or ";base64" not in header.lower():
        raise ImageMaterializationError("image data URL must use base64 encoding")
    return _decode_base64(payload, max_bytes=max_bytes)


def _decode_base64(value: str, *, max_bytes: int) -> bytes:
    # Reject oversized input before decoding so an untrusted data URL cannot
    # allocate an arbitrarily large intermediate byte buffer.
    max_encoded_bytes = ((max_bytes + 2) // 3) * 4 + 4
    if len(value) > max_encoded_bytes:
        raise ImageMaterializationError("image exceeds the configured size limit")
    try:
        image_bytes = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageMaterializationError("image base64 data is invalid") from exc
    if not image_bytes:
        raise ImageMaterializationError("image data is empty")
    if len(image_bytes) > max_bytes:
        raise ImageMaterializationError("image exceeds the configured size limit")
    return image_bytes


def _read_local_image(path: Path, max_bytes: int) -> bytes:
    try:
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise ImageMaterializationError(
                "image reference does not point to a regular file"
            )
        size = file_stat.st_size
        if size > max_bytes:
            raise ImageMaterializationError("image exceeds the configured size limit")
        image_bytes = path.read_bytes()
    except OSError as exc:
        raise ImageMaterializationError(f"could not read image file: {path}") from exc
    if not image_bytes:
        raise ImageMaterializationError("image data is empty")
    return image_bytes


async def _download_public_image(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
) -> bytes:
    resolver = await _resolve_public_http_url(url)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(
        resolver=resolver,
        use_dns_cache=False,
        ssl=ssl_context,
    )
    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            trust_env=False,
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    raise ImageMaterializationError(
                        f"image download returned HTTP {response.status}"
                    )
                content_length = response.content_length
                if content_length is not None and content_length > max_bytes:
                    raise ImageMaterializationError(
                        "image exceeds the configured size limit"
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ImageMaterializationError(
                            "image exceeds the configured size limit"
                        )
                    chunks.append(chunk)
                if not chunks:
                    raise ImageMaterializationError("image download returned an empty body")
                return b"".join(chunks)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise ImageMaterializationError("image download failed") from exc


async def _resolve_public_http_url(url: str) -> _PinnedPublicResolver:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageMaterializationError("image URL must be a valid HTTP(S) URL")
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
    if host.lower() == "localhost":
        raise ImageMaterializationError("image URL must not target localhost")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ImageMaterializationError("image URL must use a valid port") from exc

    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ImageMaterializationError("image URL host could not be resolved") from exc

    if not addresses:
        raise ImageMaterializationError("image URL host could not be resolved")
    pinned_addresses: list[_PinnedAddress] = []
    seen_addresses: set[tuple[str, int]] = set()
    for family, _, protocol, _, sockaddr in addresses:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise ImageMaterializationError(
                "image URL host returned an invalid address"
            ) from exc
        if not address.is_global:
            raise ImageMaterializationError("image URL must resolve to a public address")
        address_key = (str(address), family)
        if address_key not in seen_addresses:
            seen_addresses.add(address_key)
            pinned_addresses.append(
                _PinnedAddress(
                    host=str(address),
                    family=family,
                    protocol=protocol,
                )
            )
    if not pinned_addresses:
        raise ImageMaterializationError("image URL host could not be resolved")
    return _PinnedPublicResolver(host, tuple(pinned_addresses))


def _resolve_trusted_local_image_path(image_ref: str) -> Path:
    if image_ref.startswith("file:"):
        parsed = urlparse(image_ref.replace("\\", "/"))
        netloc = unquote(parsed.netloc or "")
        if (
            netloc
            and netloc.lower() != "localhost"
            and not re.fullmatch(r"[A-Za-z]:", netloc)
        ):
            raise ImageMaterializationError("remote file URIs are not supported")
        path_text = file_uri_to_path(image_ref)
    else:
        parsed = urlparse(image_ref)
        if parsed.scheme and not _is_windows_drive_path(image_ref):
            raise ImageMaterializationError("unsupported image reference scheme")
        path_text = image_ref

    if _is_unc_path(path_text):
        raise ImageMaterializationError("network image paths are not supported")
    try:
        path = Path(path_text).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ImageMaterializationError("could not resolve image file") from exc

    temp_root = Path(get_astrbot_temp_path()).expanduser().resolve()
    try:
        path.relative_to(temp_root)
    except ValueError as exc:
        raise ImageMaterializationError(
            "local image files must be under AstrBot temporary media storage"
        ) from exc
    return path


def _is_windows_drive_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _is_unc_path(value: str) -> bool:
    return value.startswith(("//", "\\\\"))


def _detect_image_mime_type(image_bytes: bytes) -> str:
    try:
        with PILImage.open(BytesIO(image_bytes)) as image:
            image.verify()
            image_format = str(image.format or "").upper()
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageMaterializationError("downloaded data is not a valid image") from exc

    mime_type = _FORMAT_MIME_TYPES.get(image_format)
    if mime_type is None:
        raise ImageMaterializationError(f"unsupported image format: {image_format}")
    return mime_type


__all__ = [
    "DEFAULT_IMAGE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_IMAGE_BYTES",
    "DEFAULT_PROVIDER_IMAGE_JPEG_QUALITY",
    "DEFAULT_PROVIDER_IMAGE_MAX_DIMENSION",
    "ImageMaterializationError",
    "MaterializedImage",
    "materialize_image_ref",
]

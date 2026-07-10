from __future__ import annotations

import re
from typing import Any

from tiangong_audit.contracts import SourceRef

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
SOURCE_PARENT_KEYS = {
    "referencetodatasource",
    "referencetocompletereviewreport",
    "referencetodigitalfile",
    "common:referencetodigitalfile",
    "datasources",
    "sources",
}


def resolve_source_refs(payload: Any) -> list[SourceRef]:
    """Extract source references from raw or normalized dataset JSON."""

    refs: list[SourceRef] = []
    source_dataset_ref = _source_dataset_ref(payload)
    if source_dataset_ref:
        refs.append(source_dataset_ref)
    _walk(payload, "$", "", refs)
    deduped: dict[tuple[str, str, str, str], SourceRef] = {}
    for ref in refs:
        key = (ref.source_id, ref.version, ref.locator(), ref.location)
        deduped.setdefault(key, ref)
    return list(deduped.values())


def with_external_doc_base(refs: list[SourceRef], base_url: str | None) -> list[SourceRef]:
    """Return refs with relative external_docs URIs materialized as HTTP URLs."""

    if not base_url:
        return refs
    normalized_base = base_url.rstrip("/")
    result = []
    for ref in refs:
        if not ref.url and _external_doc_name(ref.uri):
            result.append(
                SourceRef(
                    source_id=ref.source_id,
                    version=ref.version,
                    uri=ref.uri,
                    url=f"{normalized_base}/{_external_doc_name(ref.uri)}",
                    path=ref.path,
                    label=ref.label,
                    source_type=ref.source_type,
                    location=ref.location,
                )
            )
        else:
            result.append(ref)
    return result


def _source_dataset_ref(payload: Any) -> SourceRef | None:
    if not isinstance(payload, dict):
        return None
    source_dataset = payload.get("sourceDataSet")
    if not isinstance(source_dataset, dict):
        return None
    data_info = _get_path(
        source_dataset,
        "sourceInformation",
        "dataSetInformation",
    )
    admin_info = _get_path(
        source_dataset,
        "administrativeInformation",
        "publicationAndOwnership",
    )
    if not isinstance(data_info, dict):
        return None
    file_uri = _nested_uri(
        data_info.get("referenceToDigitalFile")
        or data_info.get("common:referenceToDigitalFile")
    )
    if not file_uri:
        return None
    source_id = _string_value(
        data_info.get("common:UUID")
        or data_info.get("UUID")
        or data_info.get("@UUID")
        or data_info.get("uuid")
    )
    return SourceRef(
        source_id=source_id,
        version=_string_value(
            (admin_info or {}).get("common:dataSetVersion")
            or (admin_info or {}).get("dataSetVersion")
        ),
        uri=file_uri,
        url=file_uri if file_uri.startswith(("http://", "https://")) else "",
        path=file_uri if file_uri.startswith(("file:", "/")) else "",
        label=_short_description(data_info),
        source_type="source data set digital file",
        location="$.sourceDataSet.sourceInformation.dataSetInformation.referenceToDigitalFile",
    )


def _walk(value: Any, location: str, parent_key: str, refs: list[SourceRef]) -> None:
    if isinstance(value, dict):
        source_ref = _dict_to_source_ref(value, location, parent_key)
        if source_ref:
            refs.append(source_ref)
        for key, child in value.items():
            _walk(child, f"{location}.{key}", str(key), refs)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, f"{location}[{index}]", parent_key, refs)
        return
    if isinstance(value, str):
        for match in URL_PATTERN.finditer(value):
            url = match.group(0).rstrip(".,);")
            if not _is_auditable_url(url):
                continue
            refs.append(
                SourceRef(
                    url=url,
                    label="URL in dataset text",
                    source_type="url",
                    location=location,
                )
            )


def _dict_to_source_ref(value: dict[str, Any], location: str, parent_key: str) -> SourceRef | None:
    source_type = str(value.get("@type") or value.get("type") or "")
    normalized_parent = parent_key.lower()
    parent_is_source = (
        "source" in normalized_parent or normalized_parent in SOURCE_PARENT_KEYS
    )
    has_source_id = any(key in value for key in ("@refObjectId", "refObjectId", "uuid", "@uuid"))
    has_locator = any(
        key in value
        for key in (
            "@uri",
            "uri",
            "url",
            "URL",
            "referenceToDigitalFile",
            "common:referenceToDigitalFile",
        )
    )
    uri = _string_value(
        value.get("@uri")
        or value.get("uri")
        or _nested_uri(value.get("referenceToDigitalFile"))
        or _nested_uri(value.get("common:referenceToDigitalFile"))
    )
    url = _string_value(value.get("url") or value.get("URL"))
    locator_is_source_file = bool(_external_doc_name(uri) or _external_doc_name(url))
    if not (parent_is_source or locator_is_source_file):
        return None

    if not (has_source_id or has_locator or locator_is_source_file):
        return None
    if uri.startswith("http://") or uri.startswith("https://"):
        url = uri
        uri = ""
    path = uri if uri.startswith("file:") or uri.startswith("/") else ""
    return SourceRef(
        source_id=_string_value(
            value.get("@refObjectId")
            or value.get("refObjectId")
            or value.get("uuid")
            or value.get("@uuid")
        ),
        version=_string_value(value.get("@version") or value.get("version")),
        uri=uri,
        url=url,
        path=path,
        label=_short_description(value),
        source_type=source_type or ("source data set" if parent_is_source else "source"),
        location=location,
    )


def _nested_uri(value: Any) -> str:
    if isinstance(value, dict):
        return _string_value(value.get("@uri") or value.get("uri") or value.get("url"))
    return _string_value(value)


def _get_path(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _external_doc_name(uri: str) -> str:
    text = str(uri or "").strip()
    if not text:
        return ""
    marker = "external_docs/"
    if marker in text:
        return text.split(marker, 1)[1].lstrip("/")
    if text.startswith("../external_docs/"):
        return text.removeprefix("../external_docs/").lstrip("/")
    if text.startswith("external_docs/"):
        return text.removeprefix("external_docs/").lstrip("/")
    return ""


def _is_auditable_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if "lca.jrc.it/ilcd/" in lowered or "lca.jrc.ec.europa.eu" in lowered:
        return False
    if "w3.org/2001/xmlschema" in lowered:
        return False
    if "lcdn.tiangong.earth/datasetdetail/" in lowered:
        return False
    return True


def _string_value(value: Any) -> str:
    return str(value or "").strip()


def _short_description(value: dict[str, Any]) -> str:
    for key in (
        "common:shortName",
        "shortName",
        "common:shortDescription",
        "shortDescription",
        "name",
        "title",
    ):
        text = _localized_text(value.get(key))
        if text:
            return text
    return ""


def _localized_text(value: Any) -> str:
    if isinstance(value, list):
        return " / ".join(filter(None, (_localized_text(item) for item in value)))
    if isinstance(value, dict):
        return _string_value(
            value.get("#text")
            or value.get("zh")
            or value.get("en")
            or value.get("text")
            or value.get("value")
        )
    return _string_value(value)

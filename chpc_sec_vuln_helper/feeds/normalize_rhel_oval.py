"""Converts Red Hat's official OVAL v2 XML feed
(https://www.redhat.com/security/data/oval/v2/RHEL<N>/rhel-<N>.oval.xml.bz2)
into our normalized schema (schema.py).

Rocky Linux is a binary-compatible downstream rebuild of RHEL, so this
same feed is used for Rocky too (documented approximation, endorsed by
Rocky's own security posture -- see README) rather than maintaining a
separate parser for Rocky's own smaller advisory set.

OVAL's structure: <definition> elements (one per advisory, e.g. one
RHSA) reference <test> elements by id, which reference <object>
(a package name) and <state> (a version comparison) elements, also by
id -- all four collections are siblings under <oval_definitions>. This
parser resolves those cross-references itself rather than assuming any
particular document order.

Deliberately namespace-tolerant: it matches every element by its local
tag name only (stripping the `{...}` namespace prefix ElementTree
exposes), rather than hardcoding the exact namespace URIs OVAL uses per
element group (the base oval-definitions-5 namespace for most elements,
a `#linux` extension namespace for rpminfo_test/object/state, and a
`#unix` extension namespace for the advisory/severity/cve metadata).
This trades a small amount of theoretical precision (two same-named
elements in different namespaces meaning different things -- not a
real risk in OVAL's actual structure) for robustness against getting
one of those three URIs slightly wrong, which matters here because
this parser could not be validated against a live-downloaded feed in
the environment it was written in (redhat.com was blocked). Recommend
spot-checking this normalizer's output against a real feed the first
time you run it somewhere with connectivity.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .schema import AffectedPackage, NormalizedVuln

_PLATFORM_VERSION_RE = re.compile(r"Red Hat Enterprise Linux\s+(\d+)", re.IGNORECASE)
_SEVERITY_MAP = {
    "critical": "critical",
    "important": "high",
    "moderate": "medium",
    "low": "low",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_all_local(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [el for el in root.iter() if _local(el.tag) == local_name]


def _child_local(el: ET.Element, local_name: str) -> ET.Element | None:
    for child in el:
        if _local(child.tag) == local_name:
            return child
    return None


def _text_of_child(el: ET.Element, local_name: str) -> str:
    child = _child_local(el, local_name)
    return (child.text or "").strip() if child is not None else ""


class _OvalIndex:
    """One resolved lookup pass over the whole document: test id ->
    (package name, fixed evr, arch), built once and reused for every
    definition, since building it fresh per-definition would be O(n^2)
    on a feed with tens of thousands of definitions.
    """

    def __init__(self, root: ET.Element):
        objects_by_id: dict[str, str] = {}
        for obj in _find_all_local(root, "rpminfo_object"):
            obj_id = obj.get("id")
            name = _text_of_child(obj, "name")
            if obj_id and name:
                objects_by_id[obj_id] = name

        states_by_id: dict[str, tuple[str, str]] = {}  # id -> (operation, evr)
        for state in _find_all_local(root, "rpminfo_state"):
            state_id = state.get("id")
            evr_el = _child_local(state, "evr")
            if state_id and evr_el is not None and evr_el.text:
                states_by_id[state_id] = (evr_el.get("operation", ""), evr_el.text.strip())

        self.test_to_package: dict[str, tuple[str, str]] = {}  # test id -> (name, fixed_evr)
        for test in _find_all_local(root, "rpminfo_test"):
            test_id = test.get("id")
            obj_ref_el = _child_local(test, "object")
            state_ref_el = _child_local(test, "state")
            if test_id is None or obj_ref_el is None or state_ref_el is None:
                continue
            pkg_name = objects_by_id.get(obj_ref_el.get("object_ref", ""))
            operation, evr = states_by_id.get(state_ref_el.get("state_ref", ""), ("", ""))
            if pkg_name and evr and "less than" in operation:
                self.test_to_package[test_id] = (pkg_name, evr)


def _collect_test_refs(criteria_el: ET.Element) -> list[str]:
    refs = []
    for el in criteria_el.iter():
        name = _local(el.tag)
        if name == "criterion":
            ref = el.get("test_ref")
            if ref:
                refs.append(ref)
    return refs


def parse_oval(xml_text: str, os_family: str = "rhel") -> list[NormalizedVuln]:
    root = ET.fromstring(xml_text)
    index = _OvalIndex(root)

    definitions_root = None
    for el in root:
        if _local(el.tag) == "definitions":
            definitions_root = el
            break
    if definitions_root is None:
        return []

    results: list[NormalizedVuln] = []
    for definition in definitions_root:
        if _local(definition.tag) != "definition" or definition.get("class") != "patch":
            continue

        metadata = _child_local(definition, "metadata")
        if metadata is None:
            continue

        title = _text_of_child(metadata, "title")
        description = _text_of_child(metadata, "description")

        major_versions: list[int] = []
        affected = _child_local(metadata, "affected")
        if affected is not None:
            for platform in _find_all_local(affected, "platform"):
                m = _PLATFORM_VERSION_RE.search(platform.text or "")
                if m:
                    major_versions.append(int(m.group(1)))
        if not major_versions:
            continue  # can't tell which RHEL version this applies to -- skip rather than guess

        advisory_id = definition.get("id", "")
        cve_ids: list[str] = []
        for ref in _find_all_local(metadata, "reference"):
            if ref.get("source") == "RHSA" and ref.get("ref_id"):
                advisory_id = ref.get("ref_id")
            if ref.get("source") == "CVE" and ref.get("ref_id"):
                cve_ids.append(ref.get("ref_id"))

        severity = "unknown"
        advisory_el = _child_local(metadata, "advisory")
        if advisory_el is not None:
            severity_text = _text_of_child(advisory_el, "severity").lower()
            severity = _SEVERITY_MAP.get(severity_text, "unknown")
            for cve_el in _find_all_local(advisory_el, "cve"):
                if cve_el.text and cve_el.text.strip() not in cve_ids:
                    cve_ids.append(cve_el.text.strip())

        criteria_el = _child_local(definition, "criteria")
        affected_packages: list[AffectedPackage] = []
        if criteria_el is not None:
            for test_ref in _collect_test_refs(criteria_el):
                pkg = index.test_to_package.get(test_ref)
                if pkg:
                    name, fixed_evr = pkg
                    affected_packages.append(AffectedPackage(name=name, fixed_evr=fixed_evr))

        if not affected_packages:
            continue  # nothing this tool can actually match against installed packages

        results.append(NormalizedVuln(
            id=advisory_id,
            title=title or advisory_id,
            severity=severity,
            description=description,
            os_family=os_family,
            os_major_versions=major_versions,
            source="redhat-oval",
            cve_ids=cve_ids,
            affected_packages=affected_packages,
        ))

    return results

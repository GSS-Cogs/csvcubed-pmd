"""
Pull CSV-W
----------

Functionality to pull a CSV-W and all of its relative dependencies to the local filesystem.
"""
import json
import os
from pathlib import Path
from typing import Iterable, List, Dict, Union, Set
from urllib.parse import urlparse, urljoin

from csvcubed.utils.rdf import parse_graph_retain_relative
import rdflib
import requests
from csvcubed.cli.inspect.metadataprocessor import add_triples_for_file_dependencies


def _looks_like_uri(maybe_uri: str) -> bool:
    """
    Tests whether a :class:`str` looks like a URI.

    :return: whether the :class:`str` looks like a URI or not.
    """
    parse_result = urlparse(maybe_uri)
    return parse_result.scheme != ""


def _get_context_base_url(context: Union[Dict, List, None]) -> str:
    if context is None:
        return ""
    elif not isinstance(context, list):
        return ""
    elif len(context) != 2:
        return ""

    context_obj = context[1]

    if not isinstance(context_obj, dict):
        return ""

    return context_obj.get("@base", "")


def _get_csvw_dependencies(metadata_file_url: str) -> Set[str]:
    """
    :return: A set containing all of the URLs referenced by the CSV-W converted to absolute form.
    """

    return {
        path if _looks_like_uri(path) else urljoin(metadata_file_url, path)
        for path in _get_csvw_dependencies_some_relative(metadata_file_url)
    }


def _get_csvw_dependencies_some_relative(
    metadata_file: str,
) -> Set[str]:
    """
    :return: A set of all dependencies of a CSV-W.
    """

    def _get_raw_dependencies(table_group: dict) -> Iterable[str]:

        # Embedded tables
        tables = table_group.get("tables", [])

        # If none, assume csvw represents a single table
        if not any(tables):
            tables = [table_group]

        for table in tables:
            table_url = table.get("url")
            schema = table.get("tableSchema")
            if table_url is not None and str(table_url).strip() != "":
                yield str(table_url).strip()
            if schema is not None and isinstance(schema, str) and schema.strip() != "":
                yield schema.strip()

        table_group_url = table_group.get("url")
        table_group_schema = table_group.get("schema")
        if table_group_url is not None and str(table_group_url).strip() != "":
            yield str(table_group_url).strip()
        if (
            table_group_schema is not None
            and isinstance(table_group_schema, str)
            and table_group_schema.strip() != ""
        ):
            yield table_group_schema.strip()

    table_group = _get_table_group_for_metadata_file(metadata_file)

    base_url = _get_context_base_url(table_group.get("@context"))

    dependencies = list(_get_raw_dependencies(table_group))
    dependencies += _get_rdf_file_dependencies(metadata_file)

    return {
        path if _looks_like_uri(path) else urljoin(base_url, path)
        for path in dependencies
    }


def _get_rdf_file_dependencies(metadata_file: str) -> List[str]:
    """
    Extract file dependencies defined in RDF.

    If you want to load the triples, you should not use this function as this loads all dependent triples and
    then throws most of them away.

    :return: A list of paths specifying the location of file dependencies.
    """

    table_group_graph = rdflib.ConjunctiveGraph()

    parse_graph_retain_relative(
        metadata_file,
        format="json-ld",
        graph=table_group_graph.get_context(metadata_file),
    )

    add_triples_for_file_dependencies(
        table_group_graph,
        paths_relative_to=metadata_file,
        follow_relative_path_dependencies_only=True,
    )

    return [
        str(c.identifier)
        for c in table_group_graph.contexts()
        if isinstance(c.identifier, rdflib.URIRef)
        and c.identifier != rdflib.URIRef(metadata_file)
    ]


def _get_table_group_for_metadata_file(metadata_file: str) -> Dict:
    if isinstance(metadata_file, str):
        return requests.get(metadata_file).json()
    else:
        with open(metadata_file.absolute(), "r") as f:
            return json.load(f)


def pull(csvw_metadata_url: str, output_dir: Path) -> None:
    """
    Pull all of the relative dependencies of a CSV-W metadata file down to the :obj:`output_dir`.
    """
    csvw_metadata_file_name = _get_file_name_from_url(csvw_metadata_url)
    _ensure_dir_structure_exists(output_dir)
    _download_to_file(csvw_metadata_url, output_dir / csvw_metadata_file_name)

    base_path_for_relative_files = urlparse(urljoin(csvw_metadata_url, ".")).path

    for absolute_dependency_path in _get_csvw_dependencies(csvw_metadata_url):
        relative_dependency_path = os.path.relpath(
            urlparse(absolute_dependency_path).path,
            start=base_path_for_relative_files
        )

        output_file = output_dir / relative_dependency_path
        _ensure_dir_structure_exists(output_file.parent)
        _download_to_file(absolute_dependency_path, output_file)


def _get_file_name_from_url(url: str) -> str:
    return os.path.basename(urlparse(url).path)


def _download_to_file(rel_dep_url: str, output_file: Path) -> None:
    with open(output_file, "wb+") as f:
        response = requests.get(rel_dep_url)
        for chunk in response.iter_content(chunk_size=1024):
            f.write(chunk)


def _ensure_dir_structure_exists(dir_path: Path) -> None:
    if not dir_path.exists():
        _ensure_dir_structure_exists(dir_path.parent)
        dir_path.mkdir()

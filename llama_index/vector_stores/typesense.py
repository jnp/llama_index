"""Typesense Vector store index.

An index that that is built on top of an existing vector store.

"""

import logging
from typing import Any, Callable, List, Optional, cast

from llama_index import utils
from llama_index.data_structs.node import Node
from llama_index.vector_stores.types import (
    MetadataFilters,
    NodeWithEmbedding,
    VectorStore,
    VectorStoreQuery,
    VectorStoreQueryMode,
    VectorStoreQueryResult,
)
from llama_index.vector_stores.utils import (
    DEFAULT_TEXT_KEY,
    metadata_dict_to_node,
    node_to_metadata_dict,
)

_logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "default_collection"
DEFAULT_BATCH_SIZE = 100
DEFAULT_METADATA_KEY = "metadata"


class TypesenseVectorStore(VectorStore):
    """Typesense Vector Store.

    In this vector store, embeddings and docs are stored within a
    Typesense index.

    During query time, the index uses Typesense to query for the top
    k most similar nodes.

    Args:
        client (Any): Typesense client
        tokenizer (Optional[Callable[[str], List]]): tokenizer function.

    """

    stores_text: bool = True
    is_embedding_query = False

    def __init__(
        self,
        client: Any,
        tokenizer: Optional[Callable[[str], List]] = None,
        text_key: str = DEFAULT_TEXT_KEY,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        batch_size: int = DEFAULT_BATCH_SIZE,
        metadata_key: str = DEFAULT_METADATA_KEY,
        **kwargs: Any,
    ) -> None:
        """Initialize params."""
        import_err_msg = (
            "`typesense` package not found, please run `pip install typesense`"
        )
        try:
            import typesense  # noqa: F401
        except ImportError:
            raise ImportError(import_err_msg)

        if client is not None:
            if not isinstance(client, typesense.Client):
                raise ValueError(
                    f"client should be an instance of typesense.Client, "
                    f"got {type(client)}"
                )
            self._client = cast(typesense.Client, client)
        self._tokenizer = tokenizer or utils.globals_helper.tokenizer
        self._text_key = text_key
        self._collection_name = collection_name
        self._collection = self._client.collections[self._collection_name]
        self._batch_size = batch_size
        self._metadata_key = metadata_key

    @property
    def client(self) -> Any:
        """Return Typesense client."""
        return self._client

    @property
    def collection(self) -> Any:
        """Return Typesense collection."""
        return self._collection

    def _create_collection(self, num_dim: int) -> None:
        fields = [
            {"name": "vec", "type": "float[]", "num_dim": num_dim},
            {"name": f"{self._text_key}", "type": "string"},
            {"name": ".*", "type": "auto"},
        ]
        self._client.collections.create(
            {"name": self._collection_name, "fields": fields}
        )

    def _create_upsert_docs(
        self, embedding_results: List[NodeWithEmbedding]
    ) -> List[dict]:
        upsert_docs = []
        for node in embedding_results:
            doc = {
                "id": node.id,
                "vec": node.embedding,
                f"{self._text_key}": node.node.text,
                "ref_doc_id": node.ref_doc_id,
                f"{self._metadata_key}": node_to_metadata_dict(node.node),
            }
            upsert_docs.append(doc)

        return upsert_docs

    @staticmethod
    def _to_typesense_filter(standard_filters: MetadataFilters) -> str:
        """Convert from standard dataclass to typesense filter dict."""
        for filter in standard_filters.filters:
            if filter.key == "filter_by":
                return str(filter.value)

        return ""

    def add(
        self,
        embedding_results: List[NodeWithEmbedding],
    ) -> List[str]:
        """Add embedding results to index.

        Args
            embedding_results: List[NodeWithEmbedding]: list of embedding results

        """
        from typesense.collection import Collection
        from typesense.exceptions import ObjectNotFound

        docs = self._create_upsert_docs(embedding_results)

        try:
            collection = cast(Collection, self.collection)
            collection.documents.import_(
                docs, {"action": "upsert"}, batch_size=self._batch_size
            )
        except ObjectNotFound:
            # Create the collection if it doesn't already exist
            num_dim = len(embedding_results[0].embedding)
            self._create_collection(num_dim)
            collection.documents.import_(
                docs, {"action": "upsert"}, batch_size=self._batch_size
            )

        return [result.id for result in embedding_results]

    def delete(self, ref_doc_id: str, **delete_kwargs: Any) -> None:
        """
        Delete nodes using with ref_doc_id.

        Args:
            ref_doc_id (str): The doc_id of the document to delete.

        """

        try:
            from typesense.collection import Collection

            collection = cast(Collection, self.collection)
        except ImportError:
            raise ImportError("Typesense not found. Please run `pip install typesense`")

        collection.documents.delete({"filter_by": f"ref_doc_id:={ref_doc_id}"})

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        """Query Typesense index for top k most similar nodes.

        Args:
            query (VectorStoreQuery): Vector store query object.

        """

        if query.filters:
            typesense_filter = self._to_typesense_filter(query.filters)
        else:
            typesense_filter = ""

        if query.mode is not VectorStoreQueryMode.TEXT_SEARCH:
            if query.query_embedding:
                embedded_query = [str(x) for x in query.query_embedding]
                search_requests = {
                    "searches": [
                        {
                            "collection": self._collection_name,
                            "q": "*",
                            "vector_query": f'vec:([{",".join(embedded_query)}],'
                            + f"k:{query.similarity_top_k})",
                            "filter_by": typesense_filter,
                        }
                    ]
                }
            else:
                raise ValueError("Vector search requires a query embedding")
        if query.mode is VectorStoreQueryMode.TEXT_SEARCH:
            if query.query_str:
                search_requests = {
                    "searches": [
                        {
                            "collection": self._collection_name,
                            "q": query.query_str,
                            "query_by": self._text_key,
                            "filter_by": typesense_filter,
                        }
                    ]
                }
            else:
                raise ValueError("Text search requires a query string")
        response = self._client.multi_search.perform(search_requests, {})

        top_k_nodes = []
        top_k_ids = []
        top_k_scores = None
        if query.mode is not VectorStoreQueryMode.TEXT_SEARCH:
            top_k_scores = []

        for hit in response["results"][0]["hits"]:
            document = hit["document"]
            id = document["id"]
            text = document[self._text_key]
            extra_info, node_info, relationships = metadata_dict_to_node(
                document[self._metadata_key], text_key=self._text_key
            )

            # Note that typesense distances range from 0 to 2, \
            # where 0 is most similar and 2 is most dissimilar
            if query.mode is not VectorStoreQueryMode.TEXT_SEARCH:
                score = hit["vector_distance"]

            node = Node(
                text=text,
                doc_id=id,
                extra_info=extra_info,
                node_info=node_info,
                relationships=relationships,
            )
            top_k_ids.append(id)
            top_k_nodes.append(node)
            if query.mode is not VectorStoreQueryMode.TEXT_SEARCH:
                top_k_scores.append(score)

        return VectorStoreQueryResult(
            nodes=top_k_nodes, similarities=top_k_scores, ids=top_k_ids
        )

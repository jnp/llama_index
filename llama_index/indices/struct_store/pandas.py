"""Pandas csv structured store."""

import logging
from typing import Any, Optional, Sequence

import pandas as pd

from llama_index.data_structs.node import Node
from llama_index.data_structs.table import PandasStructTable
from llama_index.indices.base_retriever import BaseRetriever
from llama_index.indices.query.base import BaseQueryEngine
from llama_index.indices.struct_store.base import BaseStructStoreIndex

logger = logging.getLogger(__name__)


class PandasIndex(BaseStructStoreIndex[PandasStructTable]):
    """Pandas Index.

    Deprecated. Please use :class:`PandasQueryEngine` instead.

    The PandasIndex is an index that stores
    a Pandas dataframe under the hood.
    Currently index "construction" is not supported.

    During query time, the user can either specify a raw SQL query
    or a natural language query to retrieve their data.

    Args:
        pandas_df (Optional[pd.DataFrame]): Pandas dataframe to use.
            See :ref:`Ref-Struct-Store` for more details.

    """

    index_struct_cls = PandasStructTable

    def __init__(
        self,
        df: pd.DataFrame,
        nodes: Optional[Sequence[Node]] = None,
        index_struct: Optional[PandasStructTable] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize params."""
        logger.warning(
            "PandasIndex is deprecated. \
            Please directly use `PandasQueryEngine(df)` instead."
        )

        if nodes is not None:
            raise ValueError("We currently do not support indexing documents or nodes.")
        self.df = df

        super().__init__(
            nodes=[],
            index_struct=index_struct,
            **kwargs,
        )

    def as_retriever(self, **kwargs: Any) -> BaseRetriever:
        raise NotImplementedError("Not supported")

    def as_query_engine(self, **kwargs: Any) -> BaseQueryEngine:
        # NOTE: lazy import
        from llama_index.query_engine.pandas_query_engine import PandasQueryEngine

        return PandasQueryEngine.from_index(self, **kwargs)

    def _build_index_from_nodes(self, nodes: Sequence[Node]) -> PandasStructTable:
        """Build index from documents."""
        index_struct = self.index_struct_cls()
        return index_struct

    def _insert(self, nodes: Sequence[Node], **insert_kwargs: Any) -> None:
        """Insert a document."""
        raise NotImplementedError("We currently do not support inserting documents.")


# legacy
GPTPandasIndex = PandasIndex

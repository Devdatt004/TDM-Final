from .db_connector import DBConnector, DB_TYPES


class ConnectorFactory:

    @staticmethod
    def create(
        source_type: str,
        connection_url,
        connect_args: dict | None = None,
    ):
        source_type = source_type.lower().strip()

        if source_type not in DB_TYPES:
            raise ValueError(
                f"Unsupported connector type: {source_type}"
            )

        # pyrefly: ignore [bad-instantiation]
        return DBConnector(
    connection_url,
    # pyrefly: ignore [unexpected-keyword]
    connect_args=connect_args,
)
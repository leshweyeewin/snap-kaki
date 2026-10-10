"""One-shot ingest of the guidance corpus into Firestore.

    python -m app.rag.ingest            # embed + write
    python -m app.rag.ingest --dry-run  # chunk only, no network

Idempotent: chunk ids are derived from the file name and heading order, so
re-running overwrites in place rather than duplicating. Run it again after
editing the corpus.

After the first run you must create the vector index once, or find_nearest
will fail. The command is printed at the end of a successful run.
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import config
from app.rag.retriever import EMBED_DIM, embed, load_corpus_chunks

logger = logging.getLogger(__name__)

INDEX_HINT = f"""
Create the vector index once (idempotent, takes a few minutes to build):

gcloud firestore indexes composite create \\
  --collection-group={config.FIRESTORE_COLLECTION} \\
  --query-scope=COLLECTION \\
  --field-config=field-path=form_id,order=ASCENDING \\
  --field-config=field-path=embedding,vector-config='{{"dimension":{EMBED_DIM},"flat":"{{}}"}}' \\
  --project={config.PROJECT_ID}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="chunk and report without embedding or writing",
    )
    parser.add_argument("--form-id", default=config.DEMO_FORM_ID)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    chunks = load_corpus_chunks(args.form_id)
    if not chunks:
        logger.error("No chunks found. Is app/rag/corpus/*.md present?")
        return 1

    logger.info("Chunked %d sections for form_id=%s", len(chunks), args.form_id)
    for c in chunks:
        logger.info("  %s  %-45s %4d chars", c.chunk_id, c.heading[:45], len(c.text))

    if args.dry_run:
        logger.info("Dry run: nothing embedded, nothing written.")
        return 0

    from google.cloud import firestore
    from google.cloud.firestore_v1.vector import Vector

    db = firestore.Client(project=config.PROJECT_ID)
    collection = db.collection(config.FIRESTORE_COLLECTION)

    written = 0
    for c in chunks:
        # Corpus text is authored by us and contains no user PII, so it is
        # embedded as written. User queries go through redaction instead.
        vector = embed(c.as_context(), task_type="RETRIEVAL_DOCUMENT")
        if len(vector) != EMBED_DIM:
            logger.error(
                "Embedding dim %d != expected %d for %s. Fix EMBED_DIM or the "
                "index config before continuing.",
                len(vector), EMBED_DIM, c.chunk_id,
            )
            return 1
        collection.document(c.chunk_id).set(
            {
                "form_id": c.form_id,
                "heading": c.heading,
                "text": c.text,
                "embedding": Vector(vector),
            }
        )
        written += 1
        logger.info("wrote %s", c.chunk_id)

    logger.info("Ingested %d chunks into %s", written, config.FIRESTORE_COLLECTION)
    print(INDEX_HINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

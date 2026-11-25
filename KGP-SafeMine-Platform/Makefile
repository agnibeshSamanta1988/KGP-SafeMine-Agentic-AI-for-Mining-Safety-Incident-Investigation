PY=.venv/bin/python -W ignore

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# models are not in the cleaned dataset: download bge-small (tokenizer/local embeddings) + MiniLM reranker once
models:  ; $(PY) -c "from huggingface_hub import snapshot_download as d; d('BAAI/bge-small-en-v1.5', local_dir='models/bge-small-en-v1.5'); d('cross-encoder/ms-marco-MiniLM-L6-v2', local_dir='models/ms-marco-MiniLM-L6-v2')"

# offline data engineering on KGP-SafeMine-Data/ (≈1 min without dense; hosted embeddings add ~5-10 min)
data: clean chunks duckdb index events-index
events-index: ; $(PY) -m safemine.ingest.build_events_index   # corpus event index for accident_stats corpus_events
clean:   ; $(PY) -m safemine.ingest.clean_pdfs
chunks:  ; $(PY) -m safemine.ingest.chunk --strategy section --size 450
duckdb:  ; $(PY) -m safemine.ingest.build_duckdb
chunks-fixed: ; $(PY) -m safemine.ingest.chunk --strategy fixed --size 450 --out data_processed/chunks_fixed450.jsonl
index:   ; $(PY) -m safemine.ingest.build_indexes

ask:     ; $(PY) -m safemine.cli "$(Q)"
api:     ; .venv/bin/uvicorn app.api:app --port 8000
ui:      ; .venv/bin/streamlit run app/ui.py
eval-retrieval: ; $(PY) -m eval.retrieval_eval
eval-cfr: ; $(PY) -m eval.cfr_eval

test:    ; $(PY) -m pytest tests -q

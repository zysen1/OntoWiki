.PHONY: ontowiki-test ontowiki-eval ontowiki-demo

ontowiki-test:
	PYTHONPATH=. pytest tests/ontowiki -v

ontowiki-eval:
	PYTHONPATH=. python -m ontowiki eval --out ontowiki/eval/results.json --check

ontowiki-demo:
	PYTHONPATH=. python -m ontowiki demo --out web/src/data/ontowiki-timeline.json --check

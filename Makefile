.PHONY: all data analysis figures clean

all: data analysis figures

data:
	python -m src.download
	python -m src.load

analysis:
	python -m src.analysis

figures:
	python -m src.figures

clean:
	rm -rf data/processed reports/results.json reports/tables/*.csv reports/figures/*.png

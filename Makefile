mtan0125_zehu4485_ngra5777.zip: report.pdf code code/algorithm code/algorithm/* code/data data
	./code/algorithm/algorithm.py
	zip -r $@ report.pdf code

report.pdf: report/report.pdf
	cp report/report.pdf .

report/report.pdf: report/report.tex report/report.sty
	cd report && pdflatex report.tex

code/data:
	mkdir -p $@

data: resources/data.zip
	unzip resources/data.zip
	rm -r __MACOSX

clean:
	rm -rf mtan0125_zehu4485_ngra5777.zip report.pdf report/report.aux report/report.log report/report.out report/report.pdf code/data data

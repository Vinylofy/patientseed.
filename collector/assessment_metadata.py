"""Restore only explicitly supplied country data; preserve the source workbook."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from collector.manual_run import load_queue


def extract(workbook, queue):
    ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(workbook) as archive:
        strings = [''.join(node.itertext()) for node in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', ns)]
        rows = {}
        for row in ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).findall('s:sheetData/s:row', ns):
            cells = {}
            for cell in row:
                value = cell.find('s:v', ns)
                text = value.text if value is not None else ''.join(cell.itertext())
                if cell.get('t') == 's' and text:
                    text = strings[int(text)]
                cells[''.join(c for c in cell.attrib['r'] if c.isalpha())] = text
            rows[int(row.attrib['r'])] = cells
    shops = {}
    for item in queue:
        raw = rows.get(item['row'], {})
        # Synthetic appended source IDs must never borrow workbook cells.
        if raw.get('A') != item['name']:
            continue
        country = {'USA':'US', 'UK':'GB', 'Nederland':'NL', 'Netherlands':'NL', 'Belgium':'BE'}.get(raw.get('B'))
        if country:
            record = {'country':country, 'country_source':f"uploaded_workbook_column_B_row_{item['row']}"}
            count = raw.get('I','')
            if isinstance(count, str) and count.isdigit():
                record['previous_reported_product_count'] = int(count)
                record['previous_count_date'] = None
            shops[str(item['row'])] = record
    return {'schema_version':1, 'source_sha256':hashlib.sha256(workbook.read_bytes()).hexdigest(), 'shops':shops}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', type=Path, required=True)
    parser.add_argument('--queue', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.workbook, load_queue(args.queue))
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('Country metadata restored for', len(result['shops']), 'source rows; queue and workbook unchanged')


if __name__ == '__main__': main()

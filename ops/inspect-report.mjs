// Local artifact-tool QA only; never deployed as a server dependency.
import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob, SpreadsheetFile} from '@oai/artifact-tool';
const input = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
await fs.mkdir(output, {recursive: true});
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
console.log((await wb.inspect({kind:'sheet', include:'id,name', maxChars:2000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:20},maxChars:1500})).ndjson);
const jobs = [['Resumen ejecutivo','A1:G9'],['Expedientes','A1:E8'],['Hallazgos','A1:H10'],['Guía de páginas','A1:H11'],['Importes','A1:F8'],['Revisión del auditor','A1:G10'],['Metodología','A1:B10'],['Trazabilidad','A1:D8']];
for (let i=0;i<jobs.length;i++) {
  const [sheetName,range] = jobs[i];
  const png = await wb.render({sheetName,range,scale:1,format:'png'});
  await fs.writeFile(path.join(output,`${i+1}.png`), new Uint8Array(await png.arrayBuffer()));
  console.log('Rendered '+sheetName);
}

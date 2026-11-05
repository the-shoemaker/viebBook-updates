"""Publish only verified installer artifacts delivered by the private build pipeline."""
import base64, hashlib, json, os, pathlib, re, subprocess, tempfile, urllib.request, xml.etree.ElementTree as ET, zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPARKLE='http://www.andymatuschak.org/xml-namespaces/sparkle'
repo=os.environ['GH_REPO'];assert repo=='the-shoemaker/viebBook-updates'
def gh(*args):return subprocess.check_output(['gh',*args],text=True)
files=subprocess.check_output(['git','diff','--name-only',os.environ['BEFORE'],os.environ['AFTER'],'--','incoming'],text=True).splitlines()
for name in files:
 p=ROOT/name
 if not p.is_file():continue
 m=json.loads(p.read_text());tag=m['tag'];asset=m['asset']
 assert re.fullmatch(r'(android-)?v\d+\.\d+\.\d+',tag)
 assert re.fullmatch(r'viebBook(-android)?-\d+\.\d+\.\d+\.(apk|dmg)',asset)
 assert re.fullmatch(r'[a-f0-9]{64}',m['sha256']) and 0<m['size']<=250*1024*1024
 request=urllib.request.Request('https://api.github.com/repos/'+repo+'/releases?per_page=100',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
 with urllib.request.urlopen(request) as response: releases=json.load(response)
 existing=[{'tagName':x['tag_name']} for x in releases]
 uploaded=False
 if any(x['tagName']==tag for x in existing):
  release=next(x for x in releases if x['tag_name']==tag)
  assets=[x for x in release['assets'] if x['name']==asset]
  if assets:
   assert assets[0]['size']==m['size'] and assets[0].get('digest')=='sha256:'+m['sha256'],'Published artifact must never be replaced'
   uploaded=True
   if not release['draft']:
    if tag.startswith('android-'):continue
    current=ET.fromstring((ROOT/'appcast.xml').read_bytes())
    if any(x.findtext('{'+SPARKLE+'}shortVersionString')==tag[1:] for x in current.findall('./channel/item')):continue
 with tempfile.TemporaryDirectory() as directory:
  directory=pathlib.Path(directory);archive=directory/'artifact.zip'
  url=urllib.request.Request(assets[0]['browser_download_url'] if uploaded else m['artifact_url'])
  assert url.full_url.startswith('https://')
  with urllib.request.urlopen(url,timeout=120) as response,archive.open('wb') as output:
   count=0;digest=hashlib.sha256()
   while chunk:=response.read(1024*1024):
    count+=len(chunk);assert count<=256*1024*1024
    digest.update(chunk);output.write(chunk)
  if uploaded:
   assert digest.hexdigest()==m['sha256']
   installer=directory/asset;archive.rename(installer)
  else:
   assert digest.hexdigest()==m['artifact_digest']
   with zipfile.ZipFile(archive) as zipped:
    assert zipped.namelist()==[m['entry']]
    info=zipped.getinfo(m['entry']);assert info.file_size==m['size']
    installer=directory/asset
    with zipped.open(info) as input,installer.open('wb') as output:
     while chunk:=input.read(1024*1024):output.write(chunk)
  assert hashlib.sha256(installer.read_bytes()).hexdigest()==m['sha256']
  feed=None
  if tag.startswith('v'):
   feed=base64.b64decode(m['appcast'],validate=True);tree=ET.fromstring(feed)
   item=next(x for x in tree.findall('./channel/item') if x.findtext('{'+SPARKLE+'}shortVersionString')==tag[1:])
   enclosure=item.find('enclosure');assert enclosure is not None
   assert enclosure.get('url')=='https://github.com/'+repo+'/releases/download/'+tag+'/'+asset
   assert enclosure.get('length')==str(m['size'])
   signature=enclosure.get('{'+SPARKLE+'}edSignature')
   command="const c=require('node:crypto'),f=require('node:fs');const k=c.createPublicKey({key:Buffer.concat([Buffer.from('302a300506032b6570032100','hex'),Buffer.from(process.argv[1],'base64')]),format:'der',type:'spki'});if(!c.verify(null,f.readFileSync(process.argv[3]),k,Buffer.from(process.argv[2],'base64')))process.exit(1);"
   subprocess.run(['node','-e',command,(ROOT/'public-ed25519.txt').read_text().strip(),signature,str(installer)],check=True)
  notes=directory/'notes.txt';notes.write_text(m['notes'])
  if not any(x['tagName']==tag for x in existing):
   gh('release','create',tag,'--draft','--title',m['title'],'--notes-file',str(notes),'--target','main')
  if not uploaded:gh('release','upload',tag,str(installer))
  gh('release','edit',tag,'--draft=false','--latest=false')
  if feed:(ROOT/'appcast.xml').write_bytes(feed)
  print('Published verified installer:',asset)

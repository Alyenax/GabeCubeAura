/** Build-time visible-copy inventory. Adds no work to the plugin runtime. */
import ts from 'typescript';
import {readFileSync,readdirSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {french} from '../src/i18n/fr';
import {translate} from '../src/i18n';
const root=path.resolve(import.meta.dirname,'..');
const props=new Set(['label','title','description','placeholder','tooltip','alt','aria-label','menuLabel',
  'strTitle','strDescription','strOKButtonText','strCancelButtonText','strDefaultLabel']);
const reverse=new Set(Object.values(french));
const neutral=/^(?:Gabe(?:Cube(?:Aura| Companion)?)?(?: Assistant)?|GLaDOS|JSAUX|Faceplate JSAUX|Steam(?:GridDB|OS)?|GitHub|Pixel Studio|PNG|GIF|RGB|API|CPU|GPU|AppID|Hex|SHA-?256|Celsius|Fahrenheit|FR|EN|USB|HDMI|CEC|Hz|KiB|MiB|GB|MB|ms|s|h|°C|\d[\d\s.,%+:–×x/-]*)$/;
const rows:{file:string,line:number,text:string}[]=[];
const englishLeaks:typeof rows=[];
// Deliberately narrow: stock French phrases in English source copy, not names
// or deliberate spoken examples. Complements dictionary coverage, not an NLP engine.
const frenchPhrase=/\b(?:mets un|active le profil|retour automatique|choisir une?|aucun(?:e)? |crée les|réglages|enregistrer les|préparation|une erreur|n’est pas|n'est pas)\b/i;
const retired=new Set(['AnimatedScreensaverStudio.tsx','ScreensaverPanel.tsx']);
const excluded:string[]=[];
function literals(node:ts.Node|undefined):string[]{
 if(!node)return[];
 if(ts.isStringLiteralLike(node))return[node.text];
 if(ts.isJsxExpression(node)||ts.isParenthesizedExpression(node))return literals(node.expression);
 if(ts.isConditionalExpression(node))return[...literals(node.whenTrue),...literals(node.whenFalse)];
 if(ts.isBinaryExpression(node)&&[ts.SyntaxKind.BarBarToken,ts.SyntaxKind.QuestionQuestionToken,ts.SyntaxKind.AmpersandAmpersandToken].includes(node.operatorToken.kind))return[...literals(node.left),...literals(node.right)];
 if(ts.isTemplateExpression(node))return[node.head.text+node.templateSpans.map((s,i)=>`{${i}}`+s.literal.text).join('')];
 return[];
}
function walk(dir:string){for(const ent of readdirSync(dir,{withFileTypes:true})){
 const full=path.join(dir,ent.name);if(ent.isDirectory()){if(ent.name!=='i18n')walk(full);continue;}
 if(!/\.tsx?$/.test(ent.name)||['i18n.ts','localized_nodes.tsx','localized_ui.tsx'].includes(ent.name))continue;
 if(retired.has(ent.name)){excluded.push(path.relative(root,full));continue;}
 const source=ts.createSourceFile(full,readFileSync(full,'utf8'),ts.ScriptTarget.Latest,true,ent.name.endsWith('tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
 const add=(n:ts.Node,values:string[])=>{for(let text of values){text=text.replace(/\s+/g,' ').trim();
  let localizedBranch=false;
  for(let parent=n.parent;parent;parent=parent.parent){
   if(ts.isConditionalExpression(parent)&&/french|language|locale|\bt\s*\(/i.test(parent.condition.getText(source))){localizedBranch=true;break;}
  }
  if(!localizedBranch&&frenchPhrase.test(text)&&translate(text,'en')===text)
   englishLeaks.push({file:path.relative(root,full),line:source.getLineAndCharacterOfPosition(n.getStart()).line+1,text});
  if(!/[a-zA-ZÀ-ÿ]{2}/.test(text)||neutral.test(text)||text==='CPU + GPU'||text in french||reverse.has(text)||translate(text,'fr')!==text||text.startsWith('@keyframes'))continue;
  rows.push({file:path.relative(root,full),line:source.getLineAndCharacterOfPosition(n.getStart()).line+1,text});}};
 function visit(n:ts.Node){
  // Spoken examples intentionally follow the separate conversation language.
  if(ts.isJsxElement(n)&&n.openingElement.attributes.properties.some(p=>ts.isJsxAttribute(p)&&p.name.getText(source)==='translate'&&p.initializer&&ts.isStringLiteral(p.initializer)&&p.initializer.text==='no'))return;
  if(ts.isJsxText(n))add(n,[n.text]);
  if(ts.isJsxAttribute(n)&&props.has(n.name.getText(source)))add(n,literals(n.initializer));
  if(ts.isJsxExpression(n)&&ts.isJsxElement(n.parent))add(n,literals(n.expression));
  if(ts.isPropertyAssignment(n)&&props.has(n.name.getText(source).replace(/^['"]|['"]$/g,'')))add(n,literals(n.initializer));
  if(ts.isCallExpression(n)&&n.expression.getText(source)==='translate')add(n,literals(n.arguments[0]));
  ts.forEachChild(n,visit);
 }visit(source);
}}
walk(path.join(root,'src'));
const unique=[...new Set(rows.map(r=>r.text))].sort();
mkdirSync(path.join(root,'out'),{recursive:true});
writeFileSync(path.join(root,'out/ui-copy-audit.json'),JSON.stringify({uncovered:unique,locations:rows,englishLeaks,excludedRetired:excluded},null,2)+'\n');
console.log(JSON.stringify({uncovered:unique.length,texts:unique,englishLeaks},null,2));
if(unique.length||englishLeaks.length)process.exitCode=1;

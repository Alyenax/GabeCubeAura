import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import type {Status} from '../../src/types';
// Execute the pure gate from the real component without loading Decky's native UI.
const source=readFileSync(new URL('../../src/components/FaceplateSetupNotice.tsx',import.meta.url),'utf8');
const gate=source.slice(source.indexOf('export function needsFaceplateSetup'),source.indexOf('export function FaceplateSetupNotice'));
const context=vm.createContext({exports:{}});vm.runInContext(ts.transpileModule(gate,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const needs=(status:unknown)=>context.exports.needsFaceplateSetup(status as Status);
test('upgraded bar setup offers a detected unconfigured Faceplate without locking bar controls',()=>{
 assert.equal(needs({onboarding_completed:true,faceplate_setup_completed:false,faceplate:{available:true}}),true);
 for(const available of [false,undefined])assert.equal(needs({onboarding_completed:true,faceplate_setup_completed:false,faceplate:{available}}),false);
 for(const completed of [true,undefined])assert.equal(needs({onboarding_completed:true,faceplate_setup_completed:completed,faceplate:{available:true}}),false);
 assert.equal(needs({onboarding_completed:false,faceplate_setup_completed:false,faceplate:{available:true}}),false);
});

test('reset then USB reconnection offers setup again, until a new confirmation',()=>{
 const reset={onboarding_completed:false,faceplate_setup_completed:false,faceplate:{available:true}};
 assert.equal(needs(reset),false);
 const barFinished={...reset,onboarding_completed:true};
 assert.equal(needs({...barFinished,faceplate:{available:false}}),false);
 assert.equal(needs({...barFinished,faceplate:{available:true}}),true);
 assert.equal(needs({...barFinished,faceplate_setup_completed:true}),false);
 assert.equal(needs({...barFinished,faceplate_setup_completed:false}),true);
});

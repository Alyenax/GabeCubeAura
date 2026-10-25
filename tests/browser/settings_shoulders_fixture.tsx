import {createRoot} from 'react-dom/client';
import {SimpleSettings} from '../../src/components/SimpleSettings';
import {setUILanguage} from '../../src/i18n';
window.__qa={live:new Set(),callbacks:[],current:null};
setUILanguage('en');
createRoot(document.getElementById('app')).render(<SimpleSettings faceplateConnected renderContent={selection=><div><h2>{selection.category} / {selection.tab}</h2><button>First {selection.tab}</button><p>Native transition and focus lifetime regression fixture.</p></div>}/>);

import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import './style.css';
import './network-extra.css';
import './knowledge-universe.css';
import './design.css';
import './interaction.css';
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);

import React from 'react';
import { createRoot } from 'react-dom/client';
import SessionApp from './SessionApp';
import './styles.css';
import './themes.css';

createRoot(document.getElementById('root')).render(<React.StrictMode><SessionApp /></React.StrictMode>);

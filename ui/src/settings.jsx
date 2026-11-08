import React, {useState} from 'react';

function readTheme() {
  try {
    const value = localStorage.getItem('theme');
    return value === 'light' || value === 'dark' ? value : 'device';
  } catch {
    return 'device';
  }
}

export function Settings() {
  const [theme, setTheme] = useState(readTheme);
  function choose(value) {
    try {
      localStorage.setItem('theme', value);
    } catch {
      value = 'device';
    }
    document.documentElement.dataset.theme = value;
    setTheme(value);
  }
  return <><h1>Settings</h1><section><h2>Appearance</h2><div className="segmented" role="group" aria-label="Appearance">{['device', 'light', 'dark'].map(value => <button key={value} type="button" aria-pressed={theme === value} onClick={() => choose(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div></section></>;
}

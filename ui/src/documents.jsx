import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export async function api(path, payload, method='POST') {
  const response = await fetch(path, payload === undefined ? {} : {method, headers: {'Content-Type': 'application/json', 'X-Factory-UI': '1'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}
export const encoded = path => path.split('/').map(encodeURIComponent).join('/');
export function Markdown({children}) {
  return <div className="markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{table: ({children}) => <div className="table-scroll" tabIndex={0}><table>{children}</table></div>}}>{children}</ReactMarkdown></div>;
}

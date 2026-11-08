import {readFileSync} from 'node:fs';
import {test, expect} from 'vitest';

function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
}
function contrast(first, second) {
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}
test('theme text and meaningful marks meet AA on their surfaces', () => {
  const css = readFileSync(new URL('./style.css', import.meta.url), 'utf8');
  const light = css.match(/:root \{\n  --background:[\s\S]*?\n\}/)[0];
  const dark = css.match(/:root\[data-theme='dark'\] \{[^}]+\}/)[0];
  const tokens = source => Object.fromEntries([...source.matchAll(/--([\w-]+):\s*(#[\da-f]{6})/gi)].map(match => [match[1], match[2]]));
  for (const theme of [tokens(light), {...tokens(light), ...tokens(dark)}]) {
    for (const surface of ['background', 'surface']) {
      for (const foreground of ['text', 'secondary', 'signal-text', 'danger-text', 'warning-text', 'success-text']) {
        expect(contrast(theme[foreground], theme[surface]), `${foreground} on ${surface}`).toBeGreaterThanOrEqual(4.5);
      }
      for (const foreground of ['signal-mark', 'danger', 'warning', 'success']) {
        expect(contrast(theme[foreground], theme[surface]), `${foreground} mark on ${surface}`).toBeGreaterThanOrEqual(3);
      }
    }
  }
});

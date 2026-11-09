import {useEffect, useState} from 'react';

export function usePhone() {
  const [phone, setPhone] = useState(() => window.matchMedia?.('(max-width: 700px)').matches || false);
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 700px)');
    if (!media) return;
    const update = () => setPhone(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return phone;
}

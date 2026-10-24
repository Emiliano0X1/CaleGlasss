import React, { useEffect, useState } from 'react';
import ForgeReconciler, { Text } from '@forge/react';
import { invoke } from '@forge/bridge';

const App = () => {
  const [data, setData] = useState(null);
  useEffect(() => {
    invoke('getText', { example: 'my-invoke-variable' }).then(setData);
  }, []);
  return (
    <>
      <Text>Hello from CaleGlasss</Text>
      <Text>{data ? data : 'Loading...'}</Text>
    </>
  );
};

ForgeReconciler.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

import { TextDecoder, TextEncoder } from 'util';

// React Router uses the browser encoding APIs missing from CRA's JSDOM version.
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;
global.IS_REACT_ACT_ENVIRONMENT = true;

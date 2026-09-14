import { createContext, useContext } from 'react';

export const GuardianAccessContext = createContext({ permissions: [], auth_mode: null, disconnect: () => {} });
export const useGuardianAccess = () => useContext(GuardianAccessContext);

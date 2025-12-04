import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import api from '@/services/api';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  // Check for existing session
  const checkSession = useCallback(async () => {
    try {
      const response = await api.get('/auth/me');
      setUser(response.data);
      return response.data;
    } catch (error) {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // Process session_id from URL hash (after OAuth redirect)
  const processSessionId = useCallback(async (sessionId) => {
    try {
      setLoading(true);
      const response = await api.post('/auth/session', { session_id: sessionId });
      setUser(response.data);
      
      // Clean URL fragment
      window.history.replaceState(null, '', window.location.pathname);
      
      // Redirect to dashboard or onboarding
      navigate('/dashboard');
      
      return response.data;
    } catch (error) {
      console.error('Session processing failed:', error);
      setUser(null);
      navigate('/');
      return null;
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  // Handle authentication on mount
  useEffect(() => {
    const handleAuth = async () => {
      // Check for session_id in URL hash
      const hash = window.location.hash;
      if (hash && hash.includes('session_id=')) {
        const sessionId = new URLSearchParams(hash.substring(1)).get('session_id');
        if (sessionId) {
          await processSessionId(sessionId);
          return;
        }
      }
      
      // Otherwise check existing session
      await checkSession();
    };

    handleAuth();
  }, [checkSession, processSessionId]);

  // Login redirect
  const login = useCallback(() => {
    const redirectUrl = `${window.location.origin}/dashboard`;
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  }, []);

  // Logout
  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setUser(null);
      navigate('/');
    }
  }, [navigate]);

  const value = {
    user,
    loading,
    login,
    logout,
    checkSession
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const api = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    // Token is sent via cookie (httpOnly), no need to add header
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized - redirect to login
      if (window.location.pathname !== '/') {
        window.location.href = '/';
      }
    }
    return Promise.reject(error);
  }
);

export default api;

// API functions
export const authApi = {
  getMe: () => api.get('/auth/me'),
  processSession: (sessionId) => api.post('/auth/session', { session_id: sessionId }),
  logout: () => api.post('/auth/logout'),
};

export const profileApi = {
  getProfile: () => api.get('/profile'),
  saveProfile: (data) => api.post('/profile', data),
};

export const analysisApi = {
  runAnalysis: (profileId) => api.post('/analyze', { profile_id: profileId }),
};

export const reportsApi = {
  listReports: () => api.get('/reports'),
  getReport: (id) => api.get(`/reports/${id}`),
  deleteReport: (id) => api.delete(`/reports/${id}`),
  updateMilestones: (id, milestones) => api.patch(`/reports/${id}/milestones`, { milestones_completed: milestones }),
};

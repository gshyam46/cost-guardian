import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { reportsApi, profileApi } from '@/services/api';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Plus, ChevronRight, Trash2, MoreVertical, RefreshCw, FileText,
  Sparkles, User, LogOut, Target, Calendar
} from 'lucide-react';

const Dashboard = () => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [reports, setReports] = useState([]);
  const [hasProfile, setHasProfile] = useState(false);
  const [loading, setLoading] = useState(true);
  const [deleteId, setDeleteId] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [reportsRes, profileRes] = await Promise.all([
          reportsApi.listReports(),
          profileApi.getProfile()
        ]);
        setReports(reportsRes.data);
        setHasProfile(!!profileRes.data);
      } catch (error) {
        console.error('Error fetching data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleDelete = async (id) => {
    try {
      await reportsApi.deleteReport(id);
      setReports(reports.filter(r => r.id !== id));
      toast.success('Report deleted');
    } catch (error) {
      toast.error('Failed to delete report');
    }
    setDeleteId(null);
  };

  const getScoreColor = (score) => {
    if (score >= 75) return 'bg-green-100 text-green-700';
    if (score >= 50) return 'bg-amber-100 text-amber-700';
    return 'bg-red-100 text-red-700';
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-pulse text-slate-600">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50" data-testid="dashboard-page">
      {/* Header */}
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-violet-500 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-semibold font-['Space_Grotesk']">FounderPath</span>
          </div>
          
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="flex items-center gap-2" data-testid="user-menu-btn">
                <div className="w-8 h-8 rounded-full bg-sky-100 flex items-center justify-center">
                  {user?.picture ? (
                    <img src={user.picture} alt={user.name} className="w-8 h-8 rounded-full" />
                  ) : (
                    <User className="w-4 h-4 text-sky-600" />
                  )}
                </div>
                <span className="hidden sm:inline text-sm">{user?.name}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <div className="px-2 py-1.5">
                <p className="text-sm font-medium">{user?.name}</p>
                <p className="text-xs text-slate-500">{user?.email}</p>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate('/onboarding')}>
                <User className="w-4 h-4 mr-2" />
                Edit Profile
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={logout} className="text-red-600" data-testid="logout-btn">
                <LogOut className="w-4 h-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {/* Welcome Section */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold font-['Space_Grotesk'] text-slate-900 mb-2">
            Welcome back, {user?.name?.split(' ')[0]}!
          </h1>
          <p className="text-slate-600">
            {hasProfile
              ? 'Track your founder journey and explore new opportunities.'
              : 'Complete your profile to discover your ideal founder niche.'}
          </p>
        </div>

        {/* Quick Actions */}
        <div className="grid sm:grid-cols-2 gap-4 mb-8">
          <Card
            className="cursor-pointer card-hover border-sky-200 bg-gradient-to-br from-sky-50 to-white"
            onClick={() => navigate('/onboarding')}
            data-testid="new-analysis-card"
          >
            <CardContent className="p-6 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-sky-500 flex items-center justify-center">
                <Plus className="w-6 h-6 text-white" />
              </div>
              <div>
                <h3 className="font-semibold font-['Space_Grotesk'] text-slate-900">
                  {hasProfile ? 'Run New Analysis' : 'Start Your Journey'}
                </h3>
                <p className="text-sm text-slate-600">
                  {hasProfile
                    ? 'Update your profile and discover new niches'
                    : 'Complete your founder profile'}
                </p>
              </div>
              <ChevronRight className="w-5 h-5 text-slate-400 ml-auto" />
            </CardContent>
          </Card>

          {hasProfile && reports.length > 0 && (
            <Card
              className="cursor-pointer card-hover"
              onClick={() => navigate(`/results/${reports[0].id}`)}
              data-testid="latest-report-card"
            >
              <CardContent className="p-6 flex items-center gap-4">
                <div className="w-12 h-12 rounded-xl bg-violet-100 flex items-center justify-center">
                  <FileText className="w-6 h-6 text-violet-600" />
                </div>
                <div>
                  <h3 className="font-semibold font-['Space_Grotesk'] text-slate-900">
                    View Latest Report
                  </h3>
                  <p className="text-sm text-slate-600">
                    {reports[0].top_niche}
                  </p>
                </div>
                <ChevronRight className="w-5 h-5 text-slate-400 ml-auto" />
              </CardContent>
            </Card>
          )}
        </div>

        {/* Reports List */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold font-['Space_Grotesk'] text-slate-900">
              Your Reports
            </h2>
            {reports.length > 0 && (
              <Badge variant="outline">{reports.length} report{reports.length !== 1 ? 's' : ''}</Badge>
            )}
          </div>

          {reports.length === 0 ? (
            <Card className="bg-slate-50 border-dashed">
              <CardContent className="py-12 text-center">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-100 flex items-center justify-center">
                  <Target className="w-8 h-8 text-slate-400" />
                </div>
                <h3 className="text-lg font-medium text-slate-900 mb-2">No reports yet</h3>
                <p className="text-slate-600 mb-4 max-w-sm mx-auto">
                  Complete your founder profile to get AI-powered niche recommendations and a personalized roadmap.
                </p>
                <Button
                  onClick={() => navigate('/onboarding')}
                  className="bg-sky-500 hover:bg-sky-600"
                  data-testid="start-journey-btn"
                >
                  <Plus className="w-4 h-4 mr-2" />
                  Start Your Journey
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {reports.map((report) => (
                <Card
                  key={report.id}
                  className="cursor-pointer card-hover"
                  onClick={() => navigate(`/results/${report.id}`)}
                  data-testid={`report-card-${report.id}`}
                >
                  <CardContent className="p-4 flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center">
                      <Target className="w-5 h-5 text-slate-600" />
                    </div>
                    
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-slate-900 truncate">
                        {report.top_niche}
                      </h3>
                      <div className="flex items-center gap-2 text-sm text-slate-500">
                        <Calendar className="w-3 h-3" />
                        {new Date(report.created_at).toLocaleDateString()}
                      </div>
                    </div>
                    
                    <Badge className={getScoreColor(report.fit_score)}>
                      {report.fit_score}% fit
                    </Badge>
                    
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" size="sm">
                          <MoreVertical className="w-4 h-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/results/${report.id}`);
                        }}>
                          <FileText className="w-4 h-4 mr-2" />
                          View Report
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteId(report.id);
                          }}
                          className="text-red-600"
                        >
                          <Trash2 className="w-4 h-4 mr-2" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Report?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. The report and all its data will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => handleDelete(deleteId)}
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default Dashboard;

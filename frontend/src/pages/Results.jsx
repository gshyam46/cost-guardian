import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { reportsApi } from '@/services/api';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  ArrowLeft, Download, Target, Map, Wrench, User, Trophy,
  ExternalLink, Clock, TrendingUp, Users, AlertCircle, CheckCircle2, Sparkles
} from 'lucide-react';

const Results = () => {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [completedMilestones, setCompletedMilestones] = useState([]);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        const response = await reportsApi.getReport(reportId);
        setReport(response.data);
        setCompletedMilestones(response.data.milestones_completed || []);
      } catch (error) {
        toast.error('Failed to load report');
        navigate('/dashboard');
      } finally {
        setLoading(false);
      }
    };

    fetchReport();
  }, [reportId, navigate]);

  const toggleMilestone = async (milestone) => {
    const newMilestones = completedMilestones.includes(milestone)
      ? completedMilestones.filter(m => m !== milestone)
      : [...completedMilestones, milestone];
    
    setCompletedMilestones(newMilestones);
    
    try {
      await reportsApi.updateMilestones(reportId, newMilestones);
    } catch (error) {
      toast.error('Failed to update milestone');
    }
  };

  const getScoreColor = (score) => {
    if (score >= 75) return 'score-high';
    if (score >= 50) return 'score-medium';
    return 'score-low';
  };

  const downloadMarkdown = () => {
    if (!report) return;
    
    let md = `# Founder Niche Report\n\n`;
    md += `Generated: ${new Date(report.created_at).toLocaleDateString()}\n\n`;
    
    md += `## Profile Summary\n\n`;
    md += `${report.profile_summary.background_summary}\n\n`;
    md += `**Key Strengths:** ${report.profile_summary.key_strengths.join(', ')}\n\n`;
    md += `**Founder Archetype:** ${report.profile_summary.ideal_founder_archetype}\n\n`;
    
    md += `## Recommended Niches\n\n`;
    report.recommended_niches.forEach((niche, i) => {
      md += `### ${i + 1}. ${niche.name} (Fit Score: ${niche.fit_score}/100)\n\n`;
      md += `${niche.description}\n\n`;
      md += `**Problem:** ${niche.problem_statement}\n\n`;
      md += `**Target Audience:** ${niche.target_audience}\n\n`;
      md += `**Why It Fits You:** ${niche.why_fits_you}\n\n`;
    });
    
    md += `## Roadmap\n\n`;
    report.roadmap.phases.forEach(phase => {
      md += `### ${phase.phase_name}\n\n`;
      md += `**Goals:**\n${phase.goals.map(g => `- ${g}`).join('\n')}\n\n`;
      md += `**Actions:**\n${phase.actions.map(a => `- ${a}`).join('\n')}\n\n`;
    });
    
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'founder-niche-report.md';
    a.click();
    URL.revokeObjectURL(url);
    
    toast.success('Report downloaded!');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-pulse text-slate-600">Loading report...</div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <p className="text-slate-600">Report not found</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/dashboard')}
              data-testid="back-btn"
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Dashboard
            </Button>
            <Separator orientation="vertical" className="h-6" />
            <div>
              <h1 className="text-lg font-semibold font-['Space_Grotesk'] text-slate-900">
                Your Founder Niche Report
              </h1>
              <p className="text-sm text-slate-500">
                Generated {new Date(report.created_at).toLocaleDateString()}
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            onClick={downloadMarkdown}
            data-testid="download-btn"
          >
            <Download className="w-4 h-4 mr-2" />
            Download
          </Button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Profile Summary */}
        <Card className="mb-8">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-sky-100 flex items-center justify-center">
                <User className="w-5 h-5 text-sky-600" />
              </div>
              <div>
                <CardTitle className="font-['Space_Grotesk']">Your Profile Summary</CardTitle>
                <CardDescription>How our AI sees your founder potential</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-slate-700 mb-4">{report.profile_summary.background_summary}</p>
            
            <div className="grid sm:grid-cols-2 gap-6">
              <div>
                <h4 className="text-sm font-medium text-slate-900 mb-2">Key Strengths</h4>
                <div className="flex flex-wrap gap-2">
                  {report.profile_summary.key_strengths.map((strength, i) => (
                    <Badge key={i} variant="secondary" className="bg-green-50 text-green-700">
                      {strength}
                    </Badge>
                  ))}
                </div>
              </div>
              <div>
                <h4 className="text-sm font-medium text-slate-900 mb-2">Founder Archetype</h4>
                <Badge className="bg-sky-100 text-sky-700">
                  {report.profile_summary.ideal_founder_archetype}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Tabs for different sections */}
        <Tabs defaultValue="niches" className="space-y-6">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="niches" className="flex items-center gap-2" data-testid="niches-tab">
              <Target className="w-4 h-4" />
              <span className="hidden sm:inline">Niches</span>
            </TabsTrigger>
            <TabsTrigger value="roadmap" className="flex items-center gap-2" data-testid="roadmap-tab">
              <Map className="w-4 h-4" />
              <span className="hidden sm:inline">Roadmap</span>
            </TabsTrigger>
            <TabsTrigger value="tools" className="flex items-center gap-2" data-testid="tools-tab">
              <Wrench className="w-4 h-4" />
              <span className="hidden sm:inline">Tools</span>
            </TabsTrigger>
          </TabsList>

          {/* Niches Tab */}
          <TabsContent value="niches" className="space-y-4">
            {report.recommended_niches.map((niche, index) => (
              <Card key={index} className="card-hover">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-3">
                        {index === 0 && (
                          <Badge className="bg-amber-100 text-amber-700">
                            <Trophy className="w-3 h-3 mr-1" />
                            Top Pick
                          </Badge>
                        )}
                        <h3 className="text-xl font-semibold font-['Space_Grotesk'] text-slate-900">
                          {niche.name}
                        </h3>
                      </div>
                      
                      <p className="text-slate-600 mb-4">{niche.description}</p>
                      
                      <div className="grid sm:grid-cols-2 gap-4 text-sm">
                        <div>
                          <div className="flex items-center gap-2 text-slate-500 mb-1">
                            <AlertCircle className="w-4 h-4" />
                            Problem
                          </div>
                          <p className="text-slate-700">{niche.problem_statement}</p>
                        </div>
                        <div>
                          <div className="flex items-center gap-2 text-slate-500 mb-1">
                            <Users className="w-4 h-4" />
                            Target Audience
                          </div>
                          <p className="text-slate-700">{niche.target_audience}</p>
                        </div>
                      </div>
                      
                      <Separator className="my-4" />
                      
                      <div>
                        <div className="flex items-center gap-2 text-slate-500 mb-1">
                          <Sparkles className="w-4 h-4" />
                          Why This Fits You
                        </div>
                        <p className="text-slate-700">{niche.why_fits_you}</p>
                      </div>
                      
                      {niche.cofounder_skills_needed?.length > 0 && (
                        <div className="mt-4">
                          <p className="text-sm text-slate-500 mb-2">Ideal co-founder skills:</p>
                          <div className="flex flex-wrap gap-2">
                            {niche.cofounder_skills_needed.map((skill, i) => (
                              <Badge key={i} variant="outline">{skill}</Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                    
                    <div className="text-center">
                      <div className={`score-badge ${getScoreColor(niche.fit_score)}`}>
                        {niche.fit_score}
                      </div>
                      <p className="text-xs text-slate-500 mt-1">Fit Score</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </TabsContent>

          {/* Roadmap Tab */}
          <TabsContent value="roadmap" className="space-y-6">
            {/* Suggested Roles */}
            {report.roadmap.suggested_roles?.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg font-['Space_Grotesk']">Career Alignment</CardTitle>
                  <CardDescription>Roles that will accelerate your founder journey</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid sm:grid-cols-2 gap-4">
                    {report.roadmap.suggested_roles.map((role, i) => (
                      <div key={i} className="p-4 bg-slate-50 rounded-lg">
                        <h4 className="font-medium text-slate-900">{role.role}</h4>
                        <p className="text-sm text-slate-500">{role.company_type}</p>
                        <p className="text-sm text-slate-600 mt-2">{role.why}</p>
                        {role.duration && (
                          <Badge variant="outline" className="mt-2">
                            <Clock className="w-3 h-3 mr-1" />
                            {role.duration}
                          </Badge>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Timeline */}
            <div className="relative">
              {report.roadmap.phases.map((phase, phaseIndex) => (
                <Card key={phaseIndex} className="mb-6 ml-8 relative">
                  {/* Timeline dot */}
                  <div className="absolute -left-8 top-6 timeline-dot" />
                  {phaseIndex < report.roadmap.phases.length - 1 && (
                    <div className="absolute -left-[1.4rem] top-8 bottom-0 w-0.5 bg-gradient-to-b from-sky-500 to-violet-500" />
                  )}
                  
                  <CardHeader>
                    <CardTitle className="text-lg font-['Space_Grotesk'] flex items-center gap-2">
                      <TrendingUp className="w-5 h-5 text-sky-500" />
                      {phase.phase_name}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Goals */}
                    <div>
                      <h4 className="text-sm font-medium text-slate-900 mb-2">Goals</h4>
                      <ul className="space-y-1">
                        {phase.goals.map((goal, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                            <CheckCircle2 className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                            {goal}
                          </li>
                        ))}
                      </ul>
                    </div>
                    
                    {/* Actions */}
                    <div>
                      <h4 className="text-sm font-medium text-slate-900 mb-2">Actions</h4>
                      <ul className="space-y-2">
                        {phase.actions.map((action, i) => (
                          <li key={i} className="flex items-start gap-2">
                            <Checkbox
                              id={`action-${phaseIndex}-${i}`}
                              checked={completedMilestones.includes(`${phaseIndex}-${i}`)}
                              onCheckedChange={() => toggleMilestone(`${phaseIndex}-${i}`)}
                            />
                            <label
                              htmlFor={`action-${phaseIndex}-${i}`}
                              className={`text-sm cursor-pointer ${completedMilestones.includes(`${phaseIndex}-${i}`) ? 'text-slate-400 line-through' : 'text-slate-600'}`}
                            >
                              {action}
                            </label>
                          </li>
                        ))}
                      </ul>
                    </div>
                    
                    {/* Resources */}
                    {phase.resources?.length > 0 && (
                      <div>
                        <h4 className="text-sm font-medium text-slate-900 mb-2">Resources</h4>
                        <div className="flex flex-wrap gap-2">
                          {phase.resources.map((resource, i) => (
                            <a
                              key={i}
                              href={resource.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-sm text-sky-600 hover:text-sky-700"
                            >
                              {resource.name}
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                    
                    {/* Deliverables */}
                    {phase.deliverables?.length > 0 && (
                      <div>
                        <h4 className="text-sm font-medium text-slate-900 mb-2">Deliverables</h4>
                        <div className="flex flex-wrap gap-2">
                          {phase.deliverables.map((deliverable, i) => (
                            <Badge key={i} variant="outline">{deliverable}</Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* First Customer Strategies */}
            {report.roadmap.first_customer_strategies?.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg font-['Space_Grotesk']">First Customer Strategies</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {report.roadmap.first_customer_strategies.map((strategy, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                        <Target className="w-4 h-4 text-sky-500 mt-0.5 flex-shrink-0" />
                        {strategy}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Tools Tab */}
          <TabsContent value="tools">
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {report.tool_recommendations.map((tool, index) => (
                <Card key={index} className="card-hover">
                  <CardContent className="p-5">
                    <div className="flex items-start justify-between mb-3">
                      <Badge
                        variant="outline"
                        className={`text-xs ${
                          tool.pricing === 'free' || tool.pricing === 'open-source'
                            ? 'bg-green-50 text-green-700 border-green-200'
                            : 'bg-amber-50 text-amber-700 border-amber-200'
                        }`}
                      >
                        {tool.pricing}
                      </Badge>
                      <span className="text-xs text-slate-400">{tool.category}</span>
                    </div>
                    
                    <h3 className="font-medium text-slate-900 mb-2">{tool.name}</h3>
                    <p className="text-sm text-slate-600 mb-3">{tool.description}</p>
                    
                    <p className="text-xs text-slate-500 mb-3">{tool.why_recommended}</p>
                    
                    {tool.url && (
                      <a
                        href={tool.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-sm text-sky-600 hover:text-sky-700"
                      >
                        Visit website
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
};

export default Results;

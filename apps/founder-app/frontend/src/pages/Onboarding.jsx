import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { profileApi, analysisApi } from '@/services/api';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { ArrowLeft, ArrowRight, Sparkles, User, Code, Heart, Clock, Target, BookOpen, Loader2 } from 'lucide-react';

const STEPS = [
  { id: 'background', title: 'Background', icon: User },
  { id: 'skills', title: 'Skills', icon: Code },
  { id: 'interests', title: 'Interests', icon: Heart },
  { id: 'constraints', title: 'Constraints', icon: Clock },
  { id: 'goals', title: 'Goals', icon: Target },
  { id: 'preferences', title: 'Preferences', icon: BookOpen },
];

const TECH_SKILLS = [
  'Python', 'JavaScript', 'TypeScript', 'React', 'Node.js', 'SQL', 'NoSQL',
  'Machine Learning', 'Data Science', 'DevOps', 'Cloud (AWS/GCP/Azure)',
  'Mobile (iOS/Android)', 'Blockchain', 'Cybersecurity', 'API Design'
];

const DOMAIN_SKILLS = [
  'Product Management', 'UX/UI Design', 'Marketing', 'Sales', 'Finance',
  'Operations', 'HR', 'Legal', 'Healthcare', 'Education', 'E-commerce',
  'SaaS', 'Enterprise', 'Consumer Apps', 'B2B', 'B2C'
];

const SOFT_SKILLS = [
  'Leadership', 'Communication', 'Problem Solving', 'Team Building',
  'Negotiation', 'Storytelling', 'Strategic Thinking', 'Adaptability',
  'Time Management', 'Networking'
];

const DOMAINS = [
  'AI/ML Infrastructure', 'Developer Tools', 'Productivity', 'Climate Tech',
  'Fintech', 'Healthcare', 'EdTech', 'Creator Economy', 'E-commerce',
  'Enterprise SaaS', 'Cybersecurity', 'Web3/Crypto', 'Gaming',
  'Future of Work', 'Real Estate Tech'
];

const TARGET_ROLES = [
  'Solo Founder', 'Technical Co-founder', 'Non-technical Co-founder',
  'Indie Hacker', 'ML Engineer', 'Product Manager', 'Growth Lead',
  'Full-stack Developer', 'Startup Employee'
];

const Onboarding = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [currentStep, setCurrentStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  
  const [formData, setFormData] = useState({
    // Background
    education: '',
    current_role: '',
    years_experience: 0,
    
    // Skills
    tech_skills: [],
    domain_skills: [],
    soft_skills: [],
    previous_projects: '',
    
    // Interests
    excited_domains: [],
    
    // Constraints
    hours_per_week: 10,
    runway_months: null,
    location: '',
    risk_appetite: 'medium',
    
    // Goals
    target_roles: [],
    
    // Resources & Preferences
    existing_portfolio: '',
    github_url: '',
    network_strength: 'moderate',
    learning_mode: 'build-first',
  });

  const updateField = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const toggleArrayItem = (field, item) => {
    setFormData(prev => {
      const arr = prev[field];
      if (arr.includes(item)) {
        return { ...prev, [field]: arr.filter(i => i !== item) };
      }
      return { ...prev, [field]: [...arr, item] };
    });
  };

  const progress = ((currentStep + 1) / STEPS.length) * 100;

  const canProceed = () => {
    switch (currentStep) {
      case 0: // Background
        return formData.education && formData.current_role;
      case 1: // Skills
        return formData.tech_skills.length > 0 || formData.domain_skills.length > 0;
      case 2: // Interests
        return formData.excited_domains.length > 0;
      case 3: // Constraints
        return formData.hours_per_week > 0;
      case 4: // Goals
        return formData.target_roles.length > 0;
      case 5: // Preferences
        return true;
      default:
        return false;
    }
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      // Save profile
      const profileResponse = await profileApi.saveProfile(formData);
      toast.success('Profile saved!');
      
      // Run analysis
      setIsAnalyzing(true);
      const analysisResponse = await analysisApi.runAnalysis(profileResponse.data.id);
      
      toast.success('Analysis complete!');
      navigate(`/results/${analysisResponse.data.report_id}`);
      
    } catch (error) {
      console.error('Error:', error);
      toast.error(error.response?.data?.detail || 'Something went wrong');
    } finally {
      setIsSubmitting(false);
      setIsAnalyzing(false);
    }
  };

  const renderStep = () => {
    switch (currentStep) {
      case 0:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="education">Education Background *</Label>
              <Input
                id="education"
                placeholder="e.g., BS Computer Science from MIT"
                value={formData.education}
                onChange={(e) => updateField('education', e.target.value)}
                data-testid="education-input"
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="current_role">Current Role *</Label>
              <Input
                id="current_role"
                placeholder="e.g., Senior Software Engineer at Google"
                value={formData.current_role}
                onChange={(e) => updateField('current_role', e.target.value)}
                data-testid="current-role-input"
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="years_experience">Years of Experience</Label>
              <Input
                id="years_experience"
                type="number"
                min="0"
                max="50"
                value={formData.years_experience}
                onChange={(e) => updateField('years_experience', parseInt(e.target.value) || 0)}
                data-testid="years-experience-input"
              />
            </div>
          </div>
        );
        
      case 1:
        return (
          <div className="space-y-6">
            <div className="space-y-3">
              <Label>Technical Skills (select all that apply)</Label>
              <div className="flex flex-wrap gap-2">
                {TECH_SKILLS.map(skill => (
                  <Badge
                    key={skill}
                    variant={formData.tech_skills.includes(skill) ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-sky-100"
                    onClick={() => toggleArrayItem('tech_skills', skill)}
                    data-testid={`tech-skill-${skill.toLowerCase().replace(/[^a-z0-9]/g, '-')}`}
                  >
                    {skill}
                  </Badge>
                ))}
              </div>
            </div>
            
            <div className="space-y-3">
              <Label>Domain Skills</Label>
              <div className="flex flex-wrap gap-2">
                {DOMAIN_SKILLS.map(skill => (
                  <Badge
                    key={skill}
                    variant={formData.domain_skills.includes(skill) ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-sky-100"
                    onClick={() => toggleArrayItem('domain_skills', skill)}
                  >
                    {skill}
                  </Badge>
                ))}
              </div>
            </div>
            
            <div className="space-y-3">
              <Label>Soft Skills</Label>
              <div className="flex flex-wrap gap-2">
                {SOFT_SKILLS.map(skill => (
                  <Badge
                    key={skill}
                    variant={formData.soft_skills.includes(skill) ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-sky-100"
                    onClick={() => toggleArrayItem('soft_skills', skill)}
                  >
                    {skill}
                  </Badge>
                ))}
              </div>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="previous_projects">Notable Projects (optional)</Label>
              <Textarea
                id="previous_projects"
                placeholder="Describe any significant projects you've built..."
                value={formData.previous_projects}
                onChange={(e) => updateField('previous_projects', e.target.value)}
                rows={3}
              />
            </div>
          </div>
        );
        
      case 2:
        return (
          <div className="space-y-6">
            <div className="space-y-3">
              <Label>Domains You're Excited About *</Label>
              <p className="text-sm text-slate-500">Select areas where you'd love to build a startup</p>
              <div className="flex flex-wrap gap-2">
                {DOMAINS.map(domain => (
                  <Badge
                    key={domain}
                    variant={formData.excited_domains.includes(domain) ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-sky-100 py-2 px-3"
                    onClick={() => toggleArrayItem('excited_domains', domain)}
                    data-testid={`domain-${domain.toLowerCase().replace(/[^a-z0-9]/g, '-')}`}
                  >
                    {domain}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        );
        
      case 3:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="hours_per_week">Hours Available Per Week *</Label>
              <Input
                id="hours_per_week"
                type="number"
                min="1"
                max="80"
                value={formData.hours_per_week}
                onChange={(e) => updateField('hours_per_week', parseInt(e.target.value) || 1)}
                data-testid="hours-per-week-input"
              />
              <p className="text-sm text-slate-500">How many hours can you dedicate to your startup journey?</p>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="runway_months">Financial Runway (months)</Label>
              <Input
                id="runway_months"
                type="number"
                min="0"
                placeholder="Leave empty if not applicable"
                value={formData.runway_months || ''}
                onChange={(e) => updateField('runway_months', e.target.value ? parseInt(e.target.value) : null)}
              />
              <p className="text-sm text-slate-500">How long can you sustain without income?</p>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="location">Location</Label>
              <Input
                id="location"
                placeholder="e.g., San Francisco, Remote"
                value={formData.location}
                onChange={(e) => updateField('location', e.target.value)}
              />
            </div>
            
            <div className="space-y-2">
              <Label>Risk Appetite *</Label>
              <Select
                value={formData.risk_appetite}
                onValueChange={(value) => updateField('risk_appetite', value)}
              >
                <SelectTrigger data-testid="risk-appetite-select">
                  <SelectValue placeholder="Select risk level" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low - Prefer stable income, side project first</SelectItem>
                  <SelectItem value="medium">Medium - Can take calculated risks</SelectItem>
                  <SelectItem value="high">High - Ready to go all in</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        );
        
      case 4:
        return (
          <div className="space-y-6">
            <div className="space-y-3">
              <Label>Target Roles *</Label>
              <p className="text-sm text-slate-500">What roles are you open to?</p>
              <div className="flex flex-wrap gap-2">
                {TARGET_ROLES.map(role => (
                  <Badge
                    key={role}
                    variant={formData.target_roles.includes(role) ? 'default' : 'outline'}
                    className="cursor-pointer hover:bg-sky-100 py-2 px-3"
                    onClick={() => toggleArrayItem('target_roles', role)}
                    data-testid={`role-${role.toLowerCase().replace(/[^a-z0-9]/g, '-')}`}
                  >
                    {role}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        );
        
      case 5:
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="existing_portfolio">Portfolio URL (optional)</Label>
              <Input
                id="existing_portfolio"
                placeholder="https://yourportfolio.com"
                value={formData.existing_portfolio}
                onChange={(e) => updateField('existing_portfolio', e.target.value)}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="github_url">GitHub URL (optional)</Label>
              <Input
                id="github_url"
                placeholder="https://github.com/username"
                value={formData.github_url}
                onChange={(e) => updateField('github_url', e.target.value)}
              />
            </div>
            
            <div className="space-y-2">
              <Label>Network Strength</Label>
              <Select
                value={formData.network_strength}
                onValueChange={(value) => updateField('network_strength', value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select network strength" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="weak">Weak - Limited professional network</SelectItem>
                  <SelectItem value="moderate">Moderate - Some industry connections</SelectItem>
                  <SelectItem value="strong">Strong - Well-connected in my field</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label>Preferred Learning Mode</Label>
              <Select
                value={formData.learning_mode}
                onValueChange={(value) => updateField('learning_mode', value)}
              >
                <SelectTrigger data-testid="learning-mode-select">
                  <SelectValue placeholder="Select learning mode" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="build-first">Build First - Learn by doing</SelectItem>
                  <SelectItem value="theory-first">Theory First - Study then apply</SelectItem>
                  <SelectItem value="mentor-led">Mentor Led - Learn from experts</SelectItem>
                  <SelectItem value="self-paced">Self Paced - Go at my own speed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        );
        
      default:
        return null;
    }
  };

  if (isAnalyzing) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <Card className="max-w-md w-full">
          <CardContent className="pt-8 pb-8 text-center">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-sky-100 flex items-center justify-center loading-pulse">
              <Sparkles className="w-8 h-8 text-sky-600" />
            </div>
            <h2 className="text-2xl font-bold font-['Space_Grotesk'] text-slate-900 mb-2">
              Analyzing Your Profile
            </h2>
            <p className="text-slate-600 mb-6">
              Our AI agents are discovering your ideal founder niche...
            </p>
            <div className="space-y-3 text-sm text-slate-500">
              <p className="animate-pulse">Analyzing your background...</p>
              <p className="animate-pulse" style={{ animationDelay: '0.5s' }}>Hunting for market opportunities...</p>
              <p className="animate-pulse" style={{ animationDelay: '1s' }}>Evaluating founder-problem fit...</p>
              <p className="animate-pulse" style={{ animationDelay: '1.5s' }}>Building your roadmap...</p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <Button
            variant="ghost"
            onClick={() => navigate('/dashboard')}
            className="mb-4"
            data-testid="back-to-dashboard-btn"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Dashboard
          </Button>
          
          <h1 className="text-2xl font-bold font-['Space_Grotesk'] text-slate-900 mb-2">
            Build Your Founder Profile
          </h1>
          <p className="text-slate-600">
            Help us understand your background so we can find your perfect niche.
          </p>
        </div>

        {/* Progress */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-600">Step {currentStep + 1} of {STEPS.length}</span>
            <span className="text-sm font-medium text-sky-600">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
          
          {/* Step indicators */}
          <div className="flex justify-between mt-4">
            {STEPS.map((step, index) => {
              const Icon = step.icon;
              const isActive = index === currentStep;
              const isCompleted = index < currentStep;
              
              return (
                <div
                  key={step.id}
                  className={`flex flex-col items-center ${index <= currentStep ? 'opacity-100' : 'opacity-40'}`}
                >
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center mb-1 step-indicator ${
                      isActive ? 'bg-sky-500 text-white active' : isCompleted ? 'bg-sky-100 text-sky-600' : 'bg-slate-200 text-slate-500'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                  </div>
                  <span className="text-xs text-slate-600 hidden sm:block">{step.title}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Form Card */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="font-['Space_Grotesk']">{STEPS[currentStep].title}</CardTitle>
            <CardDescription>
              {currentStep === 0 && 'Tell us about your professional background'}
              {currentStep === 1 && 'What skills do you bring to the table?'}
              {currentStep === 2 && 'What areas excite you the most?'}
              {currentStep === 3 && 'Help us understand your constraints'}
              {currentStep === 4 && 'What roles are you targeting?'}
              {currentStep === 5 && 'Final details and preferences'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {renderStep()}
          </CardContent>
        </Card>

        {/* Navigation */}
        <div className="flex justify-between">
          <Button
            variant="outline"
            onClick={() => setCurrentStep(prev => prev - 1)}
            disabled={currentStep === 0}
            data-testid="prev-step-btn"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Previous
          </Button>
          
          {currentStep < STEPS.length - 1 ? (
            <Button
              onClick={() => setCurrentStep(prev => prev + 1)}
              disabled={!canProceed()}
              className="bg-sky-500 hover:bg-sky-600"
              data-testid="next-step-btn"
            >
              Next
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          ) : (
            <Button
              onClick={handleSubmit}
              disabled={!canProceed() || isSubmitting}
              className="bg-sky-500 hover:bg-sky-600"
              data-testid="submit-profile-btn"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  Find My Niche
                  <Sparkles className="w-4 h-4 ml-2" />
                </>
              )}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default Onboarding;

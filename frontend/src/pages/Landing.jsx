import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ArrowRight, Target, Map, Lightbulb, Rocket, CheckCircle, Sparkles } from 'lucide-react';

const Landing = () => {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (user && !loading) {
      navigate('/dashboard');
    }
  }, [user, loading, navigate]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="animate-pulse text-slate-600">Loading...</div>
      </div>
    );
  }

  const features = [
    {
      icon: <Target className="w-6 h-6" />,
      title: 'Discover Your Niche',
      description: 'AI analyzes your background to find startup opportunities where you have an unfair advantage.'
    },
    {
      icon: <Map className="w-6 h-6" />,
      title: 'Personalized Roadmap',
      description: 'Get a concrete 3-6-12 month plan with milestones, resources, and first customer strategies.'
    },
    {
      icon: <Lightbulb className="w-6 h-6" />,
      title: 'Career Alignment',
      description: 'Learn which roles and jobs will accelerate your founder journey.'
    },
    {
      icon: <Rocket className="w-6 h-6" />,
      title: 'Free Tools Stack',
      description: 'Curated recommendations for free and low-cost tools to build your MVP.'
    }
  ];

  const steps = [
    { num: '01', title: 'Share Your Profile', desc: 'Tell us about your background, skills, and interests' },
    { num: '02', title: 'AI Analysis', desc: 'Our agents analyze your founder-market fit' },
    { num: '03', title: 'Get Your Roadmap', desc: 'Receive actionable steps to launch your startup' }
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-violet-500 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-semibold font-['Space_Grotesk']">FounderPath</span>
          </div>
          <Button 
            onClick={login}
            variant="outline" 
            className="rounded-full px-6"
            data-testid="nav-login-btn"
          >
            Sign In
          </Button>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-sky-50 text-sky-700 px-4 py-2 rounded-full text-sm font-medium mb-8">
            <Sparkles className="w-4 h-4" />
            AI-Powered Founder Discovery
          </div>
          
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold font-['Space_Grotesk'] text-slate-900 mb-6 leading-tight">
            Find Your <span className="gradient-text">Founder Niche</span><br />
            & Build With Confidence
          </h1>
          
          <p className="text-lg text-slate-600 max-w-2xl mx-auto mb-10">
            Discover the startup opportunity that matches your unique skills and background. 
            Get a personalized roadmap to go from idea to first customers.
          </p>
          
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Button 
              onClick={login}
              size="lg"
              className="rounded-full px-8 py-6 text-lg bg-sky-500 hover:bg-sky-600 shadow-lg shadow-sky-500/25"
              data-testid="hero-cta-btn"
            >
              Start Your Journey
              <ArrowRight className="w-5 h-5 ml-2" />
            </Button>
            <p className="text-sm text-slate-500">Free to use • No credit card required</p>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 px-6 bg-white">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold font-['Space_Grotesk'] text-slate-900 mb-4">
              How We Help You Succeed
            </h2>
            <p className="text-slate-600 max-w-xl mx-auto">
              Our AI agents work together to analyze your profile and create a personalized founder journey.
            </p>
          </div>
          
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {features.map((feature, index) => (
              <Card key={index} className="border-slate-200 hover:border-sky-300 transition-colors card-hover">
                <CardContent className="p-6">
                  <div className="w-12 h-12 rounded-xl bg-sky-50 text-sky-600 flex items-center justify-center mb-4">
                    {feature.icon}
                  </div>
                  <h3 className="text-lg font-semibold font-['Space_Grotesk'] text-slate-900 mb-2">
                    {feature.title}
                  </h3>
                  <p className="text-slate-600 text-sm leading-relaxed">
                    {feature.description}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold font-['Space_Grotesk'] text-slate-900 mb-4">
              Simple 3-Step Process
            </h2>
          </div>
          
          <div className="grid md:grid-cols-3 gap-8">
            {steps.map((step, index) => (
              <div key={index} className="relative">
                <div className="text-6xl font-bold font-['Space_Grotesk'] text-sky-100 mb-4">
                  {step.num}
                </div>
                <h3 className="text-xl font-semibold font-['Space_Grotesk'] text-slate-900 mb-2">
                  {step.title}
                </h3>
                <p className="text-slate-600">{step.desc}</p>
                {index < steps.length - 1 && (
                  <ArrowRight className="hidden md:block absolute top-8 -right-4 w-8 h-8 text-sky-200" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Benefits Section */}
      <section className="py-20 px-6 bg-slate-900 text-white">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold font-['Space_Grotesk'] mb-4">
              What You'll Get
            </h2>
          </div>
          
          <div className="grid sm:grid-cols-2 gap-6">
            {[
              'Top 3 startup niches matched to your skills',
              'Detailed founder-problem fit analysis',
              'Phased roadmap with concrete actions',
              'Free & low-cost tool recommendations',
              'Career path alignment suggestions',
              'First customer acquisition strategies'
            ].map((benefit, index) => (
              <div key={index} className="flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-sky-400 mt-0.5 flex-shrink-0" />
                <span className="text-slate-300">{benefit}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold font-['Space_Grotesk'] text-slate-900 mb-6">
            Ready to Find Your Path?
          </h2>
          <p className="text-lg text-slate-600 mb-8">
            Join ambitious founders who've discovered their perfect niche and built successful startups.
          </p>
          <Button 
            onClick={login}
            size="lg"
            className="rounded-full px-10 py-6 text-lg bg-sky-500 hover:bg-sky-600 shadow-lg shadow-sky-500/25"
            data-testid="footer-cta-btn"
          >
            Get Started Free
            <ArrowRight className="w-5 h-5 ml-2" />
          </Button>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-6 border-t border-slate-200">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-sky-500 to-violet-500 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="text-sm text-slate-600">FounderPath</span>
          </div>
          <p className="text-sm text-slate-500">
            © 2025 FounderPath. Built for aspiring founders.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Landing;

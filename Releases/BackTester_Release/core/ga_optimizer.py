
import random
import pandas as pd
import numpy as np
import copy
from PyQt6.QtCore import QThread, pyqtSignal
import multiprocessing
from .simulation_core import SimulationCore

# Global variable for worker processes
_worker_market_data = None
_worker_context = None

def init_worker(market_data, stock_list, start_date, end_date, base_config):
    """
    Initialize worker with shared data to avoid pickling overhead per task.
    """
    global _worker_market_data, _worker_context
    _worker_market_data = market_data
    _worker_context = {
        'stock_list': stock_list,
        'start_date': start_date,
        'end_date': end_date,
        'base_config': base_config
    }

def evaluate_worker(individual_params):
    """
    Worker function to evaluate a single individual.
    """
    global _worker_market_data, _worker_context
    
    # Merge params
    config = _worker_context['base_config'].copy()
    config.update(individual_params)
    
    # Run Simulation
    summary = SimulationCore.run(
        _worker_context['stock_list'],
        _worker_context['start_date'],
        _worker_context['end_date'],
        config,
        _worker_market_data
    )
    
    return summary.get('return_pct', -999.0)

class GAOptimizer(QThread):
    """
    Genetic Algorithm Optimizer for Trading Strategy Parameters.
    Parallelized with multiprocessing.
    """
    
    # Signals to update UI
    progress_updated = pyqtSignal(int, int, str)  # current_gen, total_gen, message
    generation_finished = pyqtSignal(int, float, dict) # gen_idx, best_fitness, best_params
    optimization_finished = pyqtSignal(dict, float) # best_params, best_return
    
    def __init__(self, engine, stock_list, start_date, end_date, base_config, 
                 param_ranges, pop_size=20, generations=10):
        super().__init__()
        self.engine = engine
        self.stock_list = stock_list
        self.start_date = start_date
        self.end_date = end_date
        self.base_config = base_config
        self.param_ranges = param_ranges
        
        # GA Hyperparameters
        self.pop_size = pop_size
        self.generations = generations
        self.mutation_rate = 0.1
        self.crossover_rate = 0.7
        self.elite_size = 2 # Number of best individuals to carry over
        
        self.running = True
        self.population = []
        self.best_global_params = None
        self.best_global_fitness = float('-inf')

    def run(self):
        """Main GA Loop"""
        # Preload Data
        self.progress_updated.emit(0, self.generations, "데이터 수집 중...")
        if not self.preload_data():
            self.optimization_finished.emit({}, 0.0)
            return

        self.init_population()
        
        # Determine Checkpoing/Workers
        cpu_count = multiprocessing.cpu_count()
        # Reserve 1 core for UI if possible, but for max speed use all
        num_workers = max(1, cpu_count - 1) 
        
        self.progress_updated.emit(0, self.generations, f"최적화 시작 (Workers: {num_workers})")
        
        # Create Pool
        # We need to ensure market_data is passed correctly
        pool = multiprocessing.Pool(
            processes=num_workers,
            initializer=init_worker,
            initargs=(self.market_data, self.stock_list, self.start_date, self.end_date, self.base_config)
        )
        
        try:
            for gen in range(self.generations):
                if not self.running:
                    break
                    
                # Evaluate Fitness (Parallel)
                # Apply map
                fitness_scores = pool.map(evaluate_worker, self.population)
                
                # Check for running status after batch
                if not self.running: break

                # Update Best
                for idx, fitness in enumerate(fitness_scores):
                    if fitness > self.best_global_fitness:
                        self.best_global_fitness = fitness
                        self.best_global_params = self.population[idx]
                
                # Report
                current_best_idx = np.argmax(fitness_scores)
                current_best_fitness = fitness_scores[current_best_idx]
                
                msg = f"세대 {gen+1}/{self.generations} 완료 (최고 수익률: {current_best_fitness:.2f}%)"
                self.progress_updated.emit(gen + 1, self.generations, msg)
                self.generation_finished.emit(gen + 1, current_best_fitness, self.population[current_best_idx])
                
                # Evolve (Selection -> Crossover -> Mutation)
                if gen < self.generations - 1:
                    self.population = self.evolve(self.population, fitness_scores)
        
        except Exception as e:
            print(f"GA Optimization Error: {e}")
        finally:
            pool.close()
            pool.join()
        
        # Finish
        if self.best_global_params:
            self.optimization_finished.emit(self.best_global_params, self.best_global_fitness)

    def preload_data(self):
        """Fetch data for all target stocks once"""
        from core.strategy_signal import process_data
        import datetime
        from PyQt6.QtWidgets import QApplication
        
        self.market_data = {}
        total = len(self.stock_list)
        
        # Calculate days needed
        today = datetime.date.today()
        if hasattr(self.start_date, 'toPyDate'):
            s_date_py = self.start_date.toPyDate()
        else:
            s_date_py = self.start_date
            
        days_needed = (today - s_date_py).days + 365
        if days_needed < 200: days_needed = 200
        
        for idx, code in enumerate(self.stock_list):
            if not self.running: return False
            
            self.progress_updated.emit(0, self.generations, f"데이터 수집 중: {code} ({idx+1}/{total})")
            
            # Using process_data directly (Rate limit handled inside or here?)
            # process_data usually handles basic fetch.
            # We assume token is valid in engine.
            df, error = process_data(code, self.engine.token, days=days_needed)
            if df is not None:
                # Pre-processing similar to BacktestEngine
                df['date_str'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
                df.set_index('date_str', inplace=True)
                self.market_data[code] = df
            
            # Rate limit
            import time
            time.sleep(0.2)
            
        return len(self.market_data) > 0

    def init_population(self):
        """Initialize random population"""
        self.population = []
        for _ in range(self.pop_size):
            individual = {}
            for key, (min_val, max_val) in self.param_ranges.items():
                if isinstance(min_val, int) and isinstance(max_val, int):
                    val = random.randint(min_val, max_val)
                else:
                    val = round(random.uniform(min_val, max_val), 1)
                individual[key] = val
            self.population.append(individual)

    def evolve(self, population, fitness_scores):
        """Create next generation"""
        next_gen = []
        
        # 1. Elitism: Keep best N
        sorted_indices = np.argsort(fitness_scores)[::-1] # Descending
        for i in range(self.elite_size):
            if i < len(sorted_indices):
                next_gen.append(population[sorted_indices[i]])
        
        # 2. Selection & Crossover
        # Tournament Selection
        while len(next_gen) < self.pop_size:
            p1 = self.tournament_select(population, fitness_scores)
            p2 = self.tournament_select(population, fitness_scores)
            
            if random.random() < self.crossover_rate:
                child = self.crossover(p1, p2)
            else:
                child = p1.copy()
            
            # Mutation
            child = self.mutate(child)
            next_gen.append(child)
            
        return next_gen

    def tournament_select(self, population, fitness_scores, k=3):
        """Select best from k random individuals"""
        indices = random.sample(range(len(population)), k)
        best_idx = indices[0]
        for idx in indices[1:]:
            if fitness_scores[idx] > fitness_scores[best_idx]:
                best_idx = idx
        return population[best_idx]

    def crossover(self, p1, p2):
        """Uniform Crossover"""
        child = {}
        for key in p1.keys():
            if random.random() < 0.5:
                child[key] = p1[key]
            else:
                child[key] = p2[key]
        return child

    def mutate(self, individual):
        """Gaussian Mutation"""
        mutated = individual.copy()
        for key, (min_val, max_val) in self.param_ranges.items():
            if random.random() < self.mutation_rate:
                # Add small noise
                sigma = (max_val - min_val) * 0.1
                current = mutated[key]
                noise = random.gauss(0, sigma)
                new_val = current + noise
                
                # Clamp
                if isinstance(min_val, int):
                    new_val = int(round(new_val))
                else:
                    new_val = round(new_val, 1)
                
                new_val = max(min_val, min(max_val, new_val))
                mutated[key] = new_val
        return mutated

    def stop(self):
        self.running = False


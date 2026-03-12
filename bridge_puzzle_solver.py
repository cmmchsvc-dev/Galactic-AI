
import heapq

def solve_bridge_puzzle():
    # state: (torch_side, tuple_of_people_on_left_side)
    # torch_side: 0 for Left, 1 for Right
    # speeds: {1, 2, 5, 10}
    
    initial_speeds = (1, 2, 5, 10)
    # Priority Queue stores: (cost, torch_side, left_side_tuple, path)
    start_state = (0, initial_speeds)
    pq = [(0, 0, initial_speeds, [])]
    visited = {}

    while pq:
        (cost, side, left_side, path) = heapq.heappop(pq)
        
        state_key = (side, tuple(sorted(left_side)))
        if state_key in visited and visited[state_key] <= cost:
            continue
        visited[state_key] = cost
        
        # Check if everyone is across (Left side is empty)
        if not left_side and side == 1:
            return cost, path

        left_list = list(left_side)
        right_list = [s for s in initial_speeds if s not in left_list]

        if side == 0: # Moving Left to Right
            # Pick 1 or 2 people from left
            import itertools
            for n in [1, 2]:
                for combo in itertools.combinations(left_list, n):
                    new_left = tuple(sorted([s for s in left_list if s not in combo]))
                    travel_time = max(combo)
                    new_path = path + [f"Cross: {combo} ({travel_time}m)"]
                    heapq.heappush(pq, (cost + travel_time, 1, new_left, new_path))
        else: # Moving Right to Left
            for n in [1, 2]:
                for combo in itertools.combinations(right_list, n):
                    new_left = tuple(sorted(left_list + list(combo)))
                    travel_time = max(combo)
                    new_path = path + [f"Return: {combo} ({travel_time}m)"]
                    heapq.heappush(pq, (cost + travel_time, 0, new_left, new_path))

    return None, None

if __name__ == "__main__":
    total_time, sequence = solve_bridge_puzzle()
    print(f"Optimal Time: {total_time} minutes")
    print("Sequence:")
    for step in sequence:
        print(f" - {step}")

//! A local model's queue: requests wait in their order for a place.
//!
//! A place is an object: it is given back when it is dropped, on any way out of a request, a thread's panic included. The
//! defect class it closes: a marker left behind held the next request back.

use std::collections::BTreeMap;
use std::sync::{Condvar, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

/// One request waiting.
#[derive(Debug)]
struct Waiter {
    group: String,
    seq: u64,
}

#[derive(Debug, Default)]
struct QueueState {
    waiting: Vec<Waiter>,
    taken: BTreeMap<String, u32>,
    next_seq: u64,
}

/// The queues of every model of this process, each by its group's name.
#[derive(Debug, Default)]
pub struct ModelQueue {
    state: Mutex<QueueState>,
    changed: Condvar,
}

impl ModelQueue {
    fn lock(&self) -> MutexGuard<'_, QueueState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn taken_in(state: &QueueState, group: &str) -> u32 {
        // absent-ok: a model nobody holds a place of has none taken: a true count, and the entry goes when it reaches zero.
        state.taken.get(group).copied().unwrap_or(0)
    }

    /// A request begins to wait in `group`'s queue.
    pub fn enter(&self, id: &str, group: &str) -> Seat<'_> {
        let mut state = self.lock();
        state.next_seq += 1;
        let seq = state.next_seq;
        state.waiting.push(Waiter { group: group.to_string(), seq });
        Seat { queue: self, id: id.to_string(), group: group.to_string(), seq }
    }

    /// How many places of `group` are taken.
    pub fn taken(&self, group: &str) -> u32 {
        Self::taken_in(&self.lock(), group)
    }
}

/// A request's place in the line. Dropped, it leaves the line, whatever the way out.
#[derive(Debug)]
pub struct Seat<'q> {
    queue: &'q ModelQueue,
    id: String,
    group: String,
    seq: u64,
}

impl<'q> Seat<'q> {
    /// How many of its queue stand before it.
    pub fn position(&self) -> usize {
        self.queue.lock().waiting.iter().filter(|waiter| waiter.group == self.group && waiter.seq < self.seq).count()
    }

    /// A place, when this request is first in line and fewer than `places` are taken.
    pub fn try_take(&self, places: u32) -> Option<Slot<'q>> {
        let mut state = self.queue.lock();
        let first = !state.waiting.iter().any(|waiter| waiter.group == self.group && waiter.seq < self.seq);
        let taken = ModelQueue::taken_in(&state, &self.group);
        if !first || taken >= places {
            return None;
        }
        state.taken.insert(self.group.clone(), taken + 1);
        Some(Slot { queue: self.queue, group: self.group.clone() })
    }

    /// Waits for anything to change, `longest` at most.
    pub fn wait(&self, longest: Duration) {
        let state = self.queue.lock();
        // The guard comes back and goes at once: what changed is read anew by the caller.
        drop(self.queue.changed.wait_timeout(state, longest).unwrap_or_else(PoisonError::into_inner));
    }

    /// The request's id.
    pub fn id(&self) -> &str {
        &self.id
    }
}

impl Drop for Seat<'_> {
    fn drop(&mut self) {
        self.queue.lock().waiting.retain(|waiter| waiter.seq != self.seq);
        self.queue.changed.notify_all();
    }
}

/// A place a request holds while it talks to its model. Dropped, it goes back and the next in line is woken.
#[derive(Debug)]
pub struct Slot<'q> {
    queue: &'q ModelQueue,
    group: String,
}

impl Drop for Slot<'_> {
    fn drop(&mut self) {
        let mut state = self.queue.lock();
        let left = ModelQueue::taken_in(&state, &self.group).saturating_sub(1);
        if left == 0 {
            state.taken.remove(&self.group);
        } else {
            state.taken.insert(self.group.clone(), left);
        }
        drop(state);
        self.queue.changed.notify_all();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[test]
    fn requests_take_their_places_in_order() {
        let queue = ModelQueue::default();
        let first = queue.enter("a", "m");
        let second = queue.enter("b", "m");
        assert_eq!((first.position(), second.position()), (0, 1));
        assert!(second.try_take(5).is_none(), "the second does not pass the first");
        let held = first.try_take(1).unwrap();
        drop(first);
        assert_eq!(second.position(), 0);
        assert!(second.try_take(1).is_none(), "one place, and it is taken");
        drop(held);
        assert!(second.try_take(1).is_some());
    }

    #[test]
    fn each_model_has_its_own_line_and_places() {
        let queue = ModelQueue::default();
        let (one, two) = (queue.enter("a", "m1"), queue.enter("b", "m2"));
        let held_one = one.try_take(1).unwrap();
        assert_eq!(two.position(), 0);
        let held_two = two.try_take(1).unwrap();
        assert_eq!((queue.taken("m1"), queue.taken("m2")), (1, 1));
        drop((held_one, held_two));
        assert_eq!((queue.taken("m1"), queue.taken("m2")), (0, 0));
    }

    #[test]
    fn a_request_that_leaves_its_line_clears_the_way() {
        let queue = ModelQueue::default();
        let first = queue.enter("a", "m");
        let second = queue.enter("b", "m");
        drop(first);
        assert_eq!(second.position(), 0);
        assert_eq!(second.id(), "b");
    }

    #[test]
    fn a_panicking_request_gives_its_place_back() {
        let queue = Arc::new(ModelQueue::default());
        let inside = Arc::clone(&queue);
        let ended = std::thread::spawn(move || {
            let seat = inside.enter("a", "m");
            let _held = seat.try_take(1).unwrap();
            panic!("a bug inside one request");
        })
        .join();
        assert!(ended.is_err());
        assert_eq!(queue.taken("m"), 0);
        assert_eq!(queue.enter("b", "m").position(), 0);
    }

    #[test]
    fn a_place_given_back_wakes_the_waiting() {
        let queue = Arc::new(ModelQueue::default());
        let first = queue.enter("a", "m");
        let held = first.try_take(1).unwrap();
        drop(first);
        let waiter = Arc::clone(&queue);
        let woken = std::thread::spawn(move || {
            let seat = waiter.enter("b", "m");
            for _ in 0..200 {
                if seat.try_take(1).is_some() {
                    return true;
                }
                seat.wait(Duration::from_millis(50));
            }
            false
        });
        std::thread::sleep(Duration::from_millis(20));
        drop(held);
        assert!(woken.join().unwrap());
    }
}

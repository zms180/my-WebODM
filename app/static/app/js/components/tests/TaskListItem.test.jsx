import React from 'react';
import { shallow } from 'enzyme';
import TaskListItem from '../TaskListItem';
import createHistory from 'history/createBrowserHistory';
const taskMock = require('../../tests/utils/MockLoader').load("task.json");

describe('<TaskListItem />', () => {
  it('renders without exploding', () => {
  	const wrapper = shallow(<TaskListItem history={createHistory()} data={taskMock} hasPermission={() => true} />);
    expect(wrapper.exists()).toBe(true);
  })

  it('renders original and resized image sizes as task details', () => {
    const task = Object.assign({}, taskMock, {
      original_image_size: {width: 4032, height: 3024},
      resize_to: 1536
    });
    const wrapper = shallow(<TaskListItem history={createHistory()} data={task} hasPermission={() => true} />);
    wrapper.setState({expanded: true});
    expect(wrapper.text()).toContain('Original Image Size:4032 × 3024 px');
    expect(wrapper.text()).toContain('Resize To:1536 px');
  })
});
